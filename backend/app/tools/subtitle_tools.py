import re

TIMECODE_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})")


def timecode_to_ms(value: str) -> int:
    match = TIMECODE_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(f"Invalid SRT timecode: {value}")
    hours, minutes, seconds, millis = [int(part) for part in match.groups()]
    return (((hours * 60) + minutes) * 60 + seconds) * 1000 + millis


def ms_to_timecode(value: int) -> str:
    millis = value % 1000
    total_seconds = value // 1000
    seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def parse_srt(text: str) -> list[dict]:
    cues: list[dict] = []
    blocks = re.split(r"\r?\n\r?\n", text.strip())
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2 or "-->" not in lines[1]:
            continue
        start_raw, end_raw = [part.strip() for part in lines[1].split("-->", maxsplit=1)]
        cues.append(
            {
                "id": f"cue-{len(cues) + 1}",
                "start_ms": timecode_to_ms(start_raw),
                "end_ms": timecode_to_ms(end_raw),
                "text": "\n".join(lines[2:]),
                "speaker": None,
                "confidence": None,
                "style": None,
            }
        )
    return cues


def cues_to_srt(cues: list[dict]) -> str:
    blocks = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{ms_to_timecode(cue['start_ms'])} --> {ms_to_timecode(cue['end_ms'])}",
                    cue["text"],
                ]
            )
        )
    return "\n\n".join(blocks)
