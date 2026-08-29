import asyncio
import json
import re
from pathlib import Path

from app.config import settings


class MediaToolError(RuntimeError):
    pass


def _tool_path(tool: str) -> str:
    configured = settings.ffmpeg.ffprobe_path if tool == "ffprobe" else settings.ffmpeg.ffmpeg_path
    if configured.exists():
        return str(configured)
    return tool


async def probe_media(file_path: Path) -> dict:
    cmd = [
        _tool_path("ffprobe"),
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(file_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise MediaToolError(stderr.decode("utf-8", errors="ignore") or "ffprobe failed")
    return json.loads(stdout.decode("utf-8"))


def duration_ms_from_probe(probe: dict) -> int | None:
    duration = probe.get("format", {}).get("duration")
    if duration is None:
        return None
    return int(float(duration) * 1000)


def video_info_from_probe(probe: dict) -> tuple[int | None, int | None, float | None]:
    for stream in probe.get("streams", []):
        if stream.get("codec_type") != "video":
            continue
        fps = None
        rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate")
        if rate and rate != "0/0":
            numerator, denominator = rate.split("/")
            if float(denominator) != 0:
                fps = float(numerator) / float(denominator)
        return stream.get("width"), stream.get("height"), fps
    return None, None, None


async def extract_audio(input_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [_tool_path("ffmpeg"), "-y", "-i", str(input_path), "-ar", "16000", "-ac", "1", str(output_path)]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise MediaToolError(stderr.decode("utf-8", errors="ignore") or "ffmpeg failed")
    return output_path


async def cut_media_segment(input_path: Path, output_path: Path, start_ms: int, end_ms: int) -> Path:
    if end_ms <= start_ms:
        raise MediaToolError("end_ms must be greater than start_ms")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _tool_path("ffmpeg"),
        "-y",
        "-ss",
        f"{start_ms / 1000:.3f}",
        "-i",
        str(input_path),
        "-t",
        f"{(end_ms - start_ms) / 1000:.3f}",
        "-c",
        "copy",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise MediaToolError(stderr.decode("utf-8", errors="ignore") or "segment cut failed")
    return output_path


async def concatenate_media(input_paths: list[Path], output_path: Path) -> Path:
    if not input_paths:
        raise MediaToolError("input_paths must not be empty")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    concat_file = output_path.with_suffix(f"{output_path.suffix}.concat.txt")
    concat_file.write_text(
        "\n".join(f"file '{path.as_posix()}'" for path in input_paths),
        encoding="utf-8",
    )
    cmd = [
        _tool_path("ffmpeg"),
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c",
        "copy",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    concat_file.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise MediaToolError(stderr.decode("utf-8", errors="ignore") or "concat failed")
    return output_path


async def remove_media_ranges(
    input_path: Path,
    output_path: Path,
    ranges: list[dict],
    duration_ms: int | None = None,
) -> Path:
    normalized = sorted(
        [
            {"start_ms": int(item["start_ms"]), "end_ms": int(item["end_ms"])}
            for item in ranges
            if int(item.get("end_ms", 0)) > int(item.get("start_ms", 0))
        ],
        key=lambda item: item["start_ms"],
    )
    if not normalized:
        raise MediaToolError("ranges must include at least one valid range")

    if duration_ms is None:
        duration_ms = duration_ms_from_probe(await probe_media(input_path))
    if not duration_ms:
        raise MediaToolError("duration_ms is required when media duration cannot be probed")

    keep_ranges: list[tuple[int, int]] = []
    cursor = 0
    for item in normalized:
        start_ms = max(0, item["start_ms"])
        end_ms = min(duration_ms, item["end_ms"])
        if start_ms > cursor:
            keep_ranges.append((cursor, start_ms))
        cursor = max(cursor, end_ms)
    if cursor < duration_ms:
        keep_ranges.append((cursor, duration_ms))
    if not keep_ranges:
        raise MediaToolError("ranges remove the entire media")

    temp_dir = output_path.parent / f"{output_path.stem}_parts"
    temp_dir.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    try:
        for index, (start_ms, end_ms) in enumerate(keep_ranges):
            part_path = temp_dir / f"part_{index:04d}{output_path.suffix}"
            parts.append(await cut_media_segment(input_path, part_path, start_ms, end_ms))
        return await concatenate_media(parts, output_path)
    finally:
        for part in parts:
            part.unlink(missing_ok=True)
        temp_dir.rmdir()


async def generate_browser_proxy(input_path: Path, output_path: Path, width: int = 1280) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    scale = f"scale='min({width},iw)':-2"
    cmd = [
        _tool_path("ffmpeg"),
        "-y",
        "-i",
        str(input_path),
        "-vf",
        scale,
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise MediaToolError(stderr.decode("utf-8", errors="ignore") or "proxy generation failed")
    return output_path


async def detect_silence(
    input_path: Path,
    threshold_db: float = -40,
    min_duration_ms: int = 500,
) -> list[dict]:
    cmd = [
        _tool_path("ffmpeg"),
        "-i",
        str(input_path),
        "-af",
        f"silencedetect=noise={threshold_db}dB:d={min_duration_ms / 1000}",
        "-f",
        "null",
        "-",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    text = stderr.decode("utf-8", errors="ignore")
    if proc.returncode != 0:
        raise MediaToolError(text or "silence detection failed")

    segments: list[dict] = []
    open_start: float | None = None
    for line in text.splitlines():
        start_match = re.search(r"silence_start:\s*([0-9.]+)", line)
        if start_match:
            open_start = float(start_match.group(1))
            continue
        end_match = re.search(r"silence_end:\s*([0-9.]+)\s*\|\s*silence_duration:\s*([0-9.]+)", line)
        if end_match and open_start is not None:
            end = float(end_match.group(1))
            duration = float(end_match.group(2))
            segments.append(
                {
                    "start_ms": int(open_start * 1000),
                    "end_ms": int(end * 1000),
                    "duration_ms": int(duration * 1000),
                }
            )
            open_start = None
    return segments
