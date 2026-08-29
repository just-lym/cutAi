import asyncio
import json
import re
import shutil
import subprocess
import threading
from pathlib import Path

from app.config import settings


class MediaToolError(RuntimeError):
    pass


_ACTIVE_PROCESSES: dict[str, subprocess.Popen[bytes]] = {}
_CANCELLED_KEYS: set[str] = set()
_PROCESS_LOCK = threading.Lock()


def clear_media_job_cancel(cancel_key: str | None) -> None:
    if not cancel_key:
        return
    with _PROCESS_LOCK:
        _CANCELLED_KEYS.discard(cancel_key)


def cancel_media_job(cancel_key: str) -> bool:
    with _PROCESS_LOCK:
        _CANCELLED_KEYS.add(cancel_key)
        proc = _ACTIVE_PROCESSES.get(cancel_key)
    if proc is None or proc.poll() is not None:
        return False
    proc.terminate()
    return True


def _is_cancelled(cancel_key: str | None) -> bool:
    if not cancel_key:
        return False
    with _PROCESS_LOCK:
        return cancel_key in _CANCELLED_KEYS


def _tool_path(tool: str) -> str:
    configured = settings.ffmpeg.ffprobe_path if tool == "ffprobe" else settings.ffmpeg.ffmpeg_path
    if configured.exists():
        return str(configured)
    return tool


def _terminate_process(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()


def _run_blocking_media_command(cmd: list[str], error_message: str, cancel_key: str | None) -> None:
    if _is_cancelled(cancel_key):
        raise MediaToolError("Render cancelled")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise MediaToolError(f"{error_message}: {exc}") from exc

    if cancel_key:
        with _PROCESS_LOCK:
            _ACTIVE_PROCESSES[cancel_key] = proc
    stderr = b""
    try:
        while True:
            if _is_cancelled(cancel_key):
                _terminate_process(proc)
                raise MediaToolError("Render cancelled")
            try:
                _, stderr = proc.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                continue
    finally:
        if cancel_key:
            with _PROCESS_LOCK:
                if _ACTIVE_PROCESSES.get(cancel_key) is proc:
                    _ACTIVE_PROCESSES.pop(cancel_key, None)

    if proc.returncode != 0 and _is_cancelled(cancel_key):
        raise MediaToolError("Render cancelled")
    if proc.returncode != 0:
        detail = stderr.decode("utf-8", errors="ignore").strip()
        raise MediaToolError(detail[-4000:] or error_message)


async def _run_media_command(cmd: list[str], error_message: str, cancel_key: str | None = None) -> None:
    await asyncio.to_thread(_run_blocking_media_command, cmd, error_message, cancel_key)


def _has_stream(probe: dict, codec_type: str) -> bool:
    return any(stream.get("codec_type") == codec_type for stream in probe.get("streams", []))


async def check_media_tool(tool: str = "ffmpeg") -> bool:
    if tool not in {"ffmpeg", "ffprobe"}:
        raise MediaToolError("tool must be ffmpeg or ffprobe")
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            [_tool_path(tool), "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        return False
    return proc.returncode == 0


async def media_tool_version(tool: str = "ffmpeg") -> str:
    if tool not in {"ffmpeg", "ffprobe"}:
        raise MediaToolError("tool must be ffmpeg or ffprobe")
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            [_tool_path(tool), "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise MediaToolError(f"{tool} is not available: {exc}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="ignore").strip()
        raise MediaToolError(detail or f"{tool} is not available")
    first_line = proc.stdout.decode("utf-8", errors="ignore").splitlines()
    return first_line[0] if first_line else f"{tool} version unavailable"


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
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise MediaToolError(f"ffprobe failed: {exc}") from exc
    if proc.returncode != 0:
        raise MediaToolError(proc.stderr.decode("utf-8", errors="ignore") or "ffprobe failed")
    return json.loads(proc.stdout.decode("utf-8"))


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
    await _run_media_command(cmd, "ffmpeg failed")
    return output_path


def _concat_file_entry(path: Path) -> str:
    safe_path = path.as_posix().replace("'", r"'\''")
    return f"file '{safe_path}'"


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
    await _run_media_command(cmd, "segment cut failed")
    return output_path


async def concatenate_media(input_paths: list[Path], output_path: Path, cancel_key: str | None = None) -> Path:
    if not input_paths:
        raise MediaToolError("input_paths must not be empty")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    concat_file = output_path.with_suffix(f"{output_path.suffix}.concat.txt")
    concat_file.write_text("\n".join(_concat_file_entry(path) for path in input_paths), encoding="utf-8")
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
    try:
        await _run_media_command(cmd, "concat failed", cancel_key)
    finally:
        concat_file.unlink(missing_ok=True)
    return output_path


async def render_edl_ranges(
    ranges: list[dict],
    asset_paths: dict[str, Path],
    output_path: Path,
    width: int = 1920,
    height: int = 1080,
    frame_rate: float | None = None,
    crf: int = 22,
    audio_fade_ms: int = 30,
    cancel_key: str | None = None,
) -> Path:
    """Render EDL source ranges as uniform segments, then concat them."""
    if not ranges:
        raise MediaToolError("edl ranges must not be empty")
    if width < 16 or height < 16:
        raise MediaToolError("width and height must be at least 16")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = output_path.parent / f"{output_path.stem}_edl_parts"
    temp_dir.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    try:
        for index, item in enumerate(ranges):
            asset_id = str(item.get("asset_id") or "")
            input_path = asset_paths.get(asset_id)
            if input_path is None:
                raise MediaToolError(f"missing asset path for range[{index}]: {asset_id}")
            start_ms = int(item.get("source_in_ms") or item.get("start_ms") or 0)
            end_ms = int(item.get("source_out_ms") or item.get("end_ms") or 0)
            if end_ms <= start_ms:
                raise MediaToolError(f"range[{index}] requires source_in_ms < source_out_ms")

            duration_s = (end_ms - start_ms) / 1000
            fade_s = min(max(0, audio_fade_ms) / 1000, duration_s / 3)
            part_path = temp_dir / f"part_{index:04d}.mp4"
            probe = await probe_media(input_path)
            video_filters = [
                f"scale={width}:{height}:force_original_aspect_ratio=decrease",
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
                "setsar=1",
            ]
            if frame_rate:
                video_filters.append(f"fps={max(1.0, min(120.0, frame_rate)):.3f}")
            cmd = [
                _tool_path("ffmpeg"),
                "-y",
                "-ss",
                f"{start_ms / 1000:.3f}",
                "-i",
                str(input_path),
                "-t",
                f"{duration_s:.3f}",
                "-vf",
                ",".join(video_filters),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
            ]
            if _has_stream(probe, "audio") and fade_s > 0:
                cmd.extend(
                    [
                        "-af",
                        (
                            f"afade=t=in:st=0:d={fade_s:.3f},"
                            f"afade=t=out:st={max(0, duration_s - fade_s):.3f}:d={fade_s:.3f}"
                        ),
                    ]
                )
            cmd.extend(
                [
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    str(min(35, max(12, crf))),
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "160k",
                    "-movflags",
                    "+faststart",
                    str(part_path),
                ]
            )
            await _run_media_command(cmd, f"edl segment render failed at range[{index}]", cancel_key)
            parts.append(part_path)
        return await concatenate_media(parts, output_path, cancel_key)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


async def render_timeline_contact_sheet(
    input_path: Path,
    output_path: Path,
    start_ms: int,
    end_ms: int,
    frames: int = 8,
    frame_width: int = 180,
) -> Path:
    if end_ms <= start_ms:
        raise MediaToolError("end_ms must be greater than start_ms")
    if frames <= 0 or frames > 24:
        raise MediaToolError("frames must be between 1 and 24")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration_s = max(0.001, (end_ms - start_ms) / 1000)
    fps = frames / duration_s
    cmd = [
        _tool_path("ffmpeg"),
        "-y",
        "-ss",
        f"{max(0, start_ms) / 1000:.3f}",
        "-i",
        str(input_path),
        "-t",
        f"{duration_s:.3f}",
        "-vf",
        f"fps={fps:.6f},scale={max(16, frame_width)}:-2,tile={frames}x1",
        "-frames:v",
        "1",
        "-q:v",
        "3",
        str(output_path),
    ]
    await _run_media_command(cmd, "timeline contact sheet failed")
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
        shutil.rmtree(temp_dir, ignore_errors=True)


async def transcode_media(
    input_path: Path,
    output_path: Path,
    width: int | None = 1280,
    start_ms: int | None = None,
    duration_ms: int | None = None,
    crf: int = 23,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [_tool_path("ffmpeg"), "-y"]
    if start_ms is not None:
        cmd.extend(["-ss", f"{max(0, start_ms) / 1000:.3f}"])
    cmd.extend(["-i", str(input_path)])
    if duration_ms is not None:
        if duration_ms <= 0:
            raise MediaToolError("duration_ms must be greater than 0")
        cmd.extend(["-t", f"{duration_ms / 1000:.3f}"])
    if width:
        cmd.extend(["-vf", f"scale='min({max(16, width)},iw)':-2"])
    cmd.extend(
        [
            "-map",
            "0:v?",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            str(min(35, max(12, crf))),
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
    )
    await _run_media_command(cmd, "transcode failed")
    return output_path


async def crop_scale_media(
    input_path: Path,
    output_path: Path,
    width: int,
    height: int,
    crop_x: int | None = None,
    crop_y: int | None = None,
    crop_width: int | None = None,
    crop_height: int | None = None,
    fit: str = "cover",
    crf: int = 22,
) -> Path:
    if width < 16 or height < 16:
        raise MediaToolError("width and height must be at least 16")
    if fit not in {"cover", "contain", "stretch"}:
        raise MediaToolError("fit must be cover, contain, or stretch")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    filters: list[str] = []
    crop_values = [crop_x, crop_y, crop_width, crop_height]
    if any(value is not None for value in crop_values):
        if not all(value is not None for value in crop_values):
            raise MediaToolError("crop_x, crop_y, crop_width, and crop_height must be provided together")
        if min(crop_x or 0, crop_y or 0) < 0 or min(crop_width or 0, crop_height or 0) <= 0:
            raise MediaToolError("crop values must be positive")
        filters.append(f"crop={int(crop_width)}:{int(crop_height)}:{int(crop_x)}:{int(crop_y)}")

    if fit == "cover":
        filters.extend(
            [
                f"scale={width}:{height}:force_original_aspect_ratio=increase",
                f"crop={width}:{height}",
            ]
        )
    elif fit == "contain":
        filters.extend(
            [
                f"scale={width}:{height}:force_original_aspect_ratio=decrease",
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            ]
        )
    else:
        filters.append(f"scale={width}:{height}")

    cmd = [
        _tool_path("ffmpeg"),
        "-y",
        "-i",
        str(input_path),
        "-vf",
        ",".join(filters),
        "-map",
        "0:v?",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        str(min(35, max(12, crf))),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    await _run_media_command(cmd, "crop/scale failed")
    return output_path


async def normalize_audio_loudness(
    input_path: Path,
    output_path: Path,
    target_i: float = -16.0,
    target_tp: float = -1.5,
    target_lra: float = 11.0,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    loudnorm = f"loudnorm=I={target_i:.1f}:TP={target_tp:.1f}:LRA={target_lra:.1f}"
    cmd = [
        _tool_path("ffmpeg"),
        "-y",
        "-i",
        str(input_path),
        "-filter:a",
        loudnorm,
        "-map",
        "0:v?",
        "-map",
        "0:a?",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    await _run_media_command(cmd, "loudness normalization failed")
    return output_path


async def change_media_volume(input_path: Path, output_path: Path, volume: float = 1.0) -> Path:
    if volume < 0 or volume > 3:
        raise MediaToolError("volume must be between 0 and 3")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _tool_path("ffmpeg"),
        "-y",
        "-i",
        str(input_path),
        "-filter:a",
        f"volume={volume:.3f}",
        "-map",
        "0:v?",
        "-map",
        "0:a?",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    await _run_media_command(cmd, "volume change failed")
    return output_path


async def fade_media_audio(
    input_path: Path,
    output_path: Path,
    fade_type: str,
    start_ms: int,
    duration_ms: int,
) -> Path:
    if fade_type not in {"in", "out"}:
        raise MediaToolError("fade_type must be 'in' or 'out'")
    if start_ms < 0 or duration_ms <= 0:
        raise MediaToolError("start_ms must be >= 0 and duration_ms must be > 0")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _tool_path("ffmpeg"),
        "-y",
        "-i",
        str(input_path),
        "-filter:a",
        f"afade=t={fade_type}:st={start_ms / 1000:.3f}:d={duration_ms / 1000:.3f}",
        "-map",
        "0:v?",
        "-map",
        "0:a?",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    await _run_media_command(cmd, "audio fade failed")
    return output_path


async def extract_frame(
    input_path: Path,
    output_path: Path,
    at_ms: int = 0,
    width: int | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [_tool_path("ffmpeg"), "-y", "-ss", f"{max(0, at_ms) / 1000:.3f}", "-i", str(input_path)]
    if width:
        cmd.extend(["-vf", f"scale='min({max(16, width)},iw)':-2"])
    cmd.extend(["-frames:v", "1", "-q:v", "2", str(output_path)])
    await _run_media_command(cmd, "frame extraction failed")
    return output_path


async def extract_thumbnail_sequence(
    input_path: Path,
    output_dir: Path,
    every_ms: int = 1000,
    width: int = 240,
    limit: int = 60,
) -> list[Path]:
    if every_ms <= 0:
        raise MediaToolError("every_ms must be greater than 0")
    if limit <= 0 or limit > 300:
        raise MediaToolError("limit must be between 1 and 300")
    output_dir.mkdir(parents=True, exist_ok=True)
    pattern = output_dir / "thumb_%04d.jpg"
    fps = 1000 / every_ms
    cmd = [
        _tool_path("ffmpeg"),
        "-y",
        "-i",
        str(input_path),
        "-vf",
        f"fps={fps:.6f},scale='min({max(16, width)},iw)':-2",
        "-frames:v",
        str(limit),
        "-q:v",
        "3",
        str(pattern),
    ]
    await _run_media_command(cmd, "thumbnail sequence extraction failed")
    return sorted(output_dir.glob("thumb_*.jpg"))


async def detect_scene_changes(
    input_path: Path,
    threshold: float = 0.35,
    min_gap_ms: int = 500,
) -> list[dict]:
    if threshold <= 0 or threshold >= 1:
        raise MediaToolError("threshold must be between 0 and 1")
    cmd = [
        _tool_path("ffmpeg"),
        "-i",
        str(input_path),
        "-vf",
        f"select='gt(scene,{threshold:.3f})',showinfo",
        "-f",
        "null",
        "-",
    ]
    proc = await asyncio.to_thread(
        subprocess.run,
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    text = proc.stderr.decode("utf-8", errors="ignore")
    if proc.returncode != 0:
        raise MediaToolError(text or "scene detection failed")

    scenes: list[dict] = []
    last_ms = -min_gap_ms
    for line in text.splitlines():
        match = re.search(r"pts_time:([0-9.]+)", line)
        if not match:
            continue
        at_ms = int(float(match.group(1)) * 1000)
        if at_ms - last_ms >= min_gap_ms:
            scenes.append({"at_ms": at_ms})
            last_ms = at_ms
    return scenes


def _ffmpeg_filter_path(path: Path) -> str:
    value = path.resolve().as_posix()
    value = value.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    return value


async def burn_subtitles(
    input_path: Path,
    subtitle_path: Path,
    output_path: Path,
    font_size: int = 24,
    primary_color: str = "&H00FFFFFF",
    outline_color: str = "&H00000000",
    cancel_key: str | None = None,
) -> Path:
    if not subtitle_path.exists():
        raise MediaToolError("subtitle file does not exist")
    if font_size < 8 or font_size > 96:
        raise MediaToolError("font_size must be between 8 and 96")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    style = (
        f"FontSize={font_size},PrimaryColour={primary_color},"
        f"OutlineColour={outline_color},BorderStyle=1,Outline=2,Shadow=0"
    )
    cmd = [
        _tool_path("ffmpeg"),
        "-y",
        "-i",
        str(input_path),
        "-vf",
        f"subtitles='{_ffmpeg_filter_path(subtitle_path)}':force_style='{style}'",
        "-map",
        "0:v?",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    await _run_media_command(cmd, "subtitle burn-in failed", cancel_key)
    return output_path


async def overlay_media(
    base_path: Path,
    overlay_path: Path,
    output_path: Path,
    position_ms: int,
    duration_ms: int,
    source_in_ms: int = 0,
    x: int = 0,
    y: int = 0,
    overlay_width: int = 480,
    cancel_key: str | None = None,
) -> Path:
    if position_ms < 0 or source_in_ms < 0 or duration_ms <= 0:
        raise MediaToolError("position_ms/source_in_ms must be >= 0 and duration_ms must be > 0")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    start_s = position_ms / 1000
    end_s = (position_ms + duration_ms) / 1000
    filter_graph = (
        f"[1:v]scale={max(16, overlay_width)}:-2,setpts=PTS-STARTPTS+{start_s:.3f}/TB[ov];"
        f"[0:v][ov]overlay={x}:{y}:enable='between(t,{start_s:.3f},{end_s:.3f})':eof_action=pass[v]"
    )
    image_suffixes = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    cmd = [
        _tool_path("ffmpeg"),
        "-y",
        "-i",
        str(base_path),
    ]
    if overlay_path.suffix.lower() in image_suffixes:
        cmd.extend(["-loop", "1", "-t", f"{duration_ms / 1000:.3f}"])
    else:
        cmd.extend(["-ss", f"{source_in_ms / 1000:.3f}", "-t", f"{duration_ms / 1000:.3f}"])
    cmd.extend(
        [
            "-i",
            str(overlay_path),
            "-filter_complex",
            filter_graph,
            "-map",
            "[v]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    await _run_media_command(cmd, "overlay failed", cancel_key)
    return output_path


async def apply_timeline_overlays(
    base_path: Path,
    overlays: list[dict],
    asset_paths: dict[str, Path],
    output_path: Path,
    canvas_width: int = 1920,
    cancel_key: str | None = None,
) -> Path:
    if not overlays:
        raise MediaToolError("overlays must not be empty")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = output_path.parent / f"{output_path.stem}_overlay_steps"
    temp_dir.mkdir(parents=True, exist_ok=True)
    current = base_path
    try:
        valid_overlays = [
            item
            for item in sorted(overlays, key=lambda clip: int(clip.get("timeline_start_ms") or 0))
            if item.get("asset_id")
            and int(item.get("timeline_end_ms") or 0) > int(item.get("timeline_start_ms") or 0)
        ]
        if not valid_overlays:
            raise MediaToolError("overlays must include at least one valid clip")
        for index, clip in enumerate(valid_overlays):
            overlay_path = asset_paths.get(str(clip["asset_id"]))
            if overlay_path is None:
                raise MediaToolError(f"missing overlay asset path: {clip['asset_id']}")
            transform = clip.get("transform") if isinstance(clip.get("transform"), dict) else {}
            scale = float(transform.get("scale") or 1.0)
            overlay_width = int(transform.get("width") or max(16, min(canvas_width, round(canvas_width * 0.32 * scale))))
            next_path = output_path if index == len(valid_overlays) - 1 else temp_dir / f"overlay_{index:04d}.mp4"
            current = await overlay_media(
                current,
                overlay_path,
                next_path,
                position_ms=int(clip.get("timeline_start_ms") or 0),
                duration_ms=int(clip.get("timeline_end_ms") or 0) - int(clip.get("timeline_start_ms") or 0),
                source_in_ms=int(clip.get("source_in_ms") or 0),
                x=int(transform.get("x") or 0),
                y=int(transform.get("y") or 0),
                overlay_width=overlay_width,
                cancel_key=cancel_key,
            )
        return output_path
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


async def mix_timeline_audio(
    base_path: Path,
    audio_clips: list[dict],
    asset_paths: dict[str, Path],
    output_path: Path,
    cancel_key: str | None = None,
) -> Path:
    valid_clips = [
        clip
        for clip in sorted(audio_clips, key=lambda item: int(item.get("timeline_start_ms") or 0))
        if clip.get("asset_id")
        and int(clip.get("timeline_end_ms") or 0) > int(clip.get("timeline_start_ms") or 0)
    ]
    if not valid_clips:
        raise MediaToolError("audio_clips must include at least one valid clip")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    base_probe = await probe_media(base_path)
    has_base_audio = _has_stream(base_probe, "audio")
    cmd = [_tool_path("ffmpeg"), "-y", "-i", str(base_path)]
    included: list[dict] = []
    for clip in valid_clips:
        audio_path = asset_paths.get(str(clip["asset_id"]))
        if audio_path is None:
            raise MediaToolError(f"missing audio asset path: {clip['asset_id']}")
        probe = await probe_media(audio_path)
        if not _has_stream(probe, "audio"):
            continue
        duration_ms = int(clip.get("timeline_end_ms") or 0) - int(clip.get("timeline_start_ms") or 0)
        cmd.extend(
            [
                "-ss",
                f"{int(clip.get('source_in_ms') or 0) / 1000:.3f}",
                "-t",
                f"{duration_ms / 1000:.3f}",
                "-i",
                str(audio_path),
            ]
        )
        included.append(clip)

    if not included:
        raise MediaToolError("audio_clips do not reference assets with audio streams")

    filters: list[str] = []
    labels: list[str] = []
    if has_base_audio:
        filters.append("[0:a]volume=1.000[basea]")
        labels.append("[basea]")

    for input_index, clip in enumerate(included, start=1):
        label = f"a{input_index}"
        delay_ms = int(clip.get("timeline_start_ms") or 0)
        volume = max(0.0, min(2.0, float(clip.get("volume") if clip.get("volume") is not None else 0.7)))
        filters.append(
            f"[{input_index}:a]asetpts=PTS-STARTPTS,volume={volume:.3f},"
            f"adelay={delay_ms}:all=1[{label}]"
        )
        labels.append(f"[{label}]")

    filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:dropout_transition=0[mixa]")
    cmd.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "0:v:0",
            "-map",
            "[mixa]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    await _run_media_command(cmd, "audio mix failed", cancel_key)
    return output_path


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
    await _run_media_command(cmd, "proxy generation failed")
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
    proc = await asyncio.to_thread(
        subprocess.run,
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    text = proc.stderr.decode("utf-8", errors="ignore")
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
