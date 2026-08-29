from itertools import pairwise
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from app.agents.tools.context import AgentToolContext
from app.agents.tools.schema import AgentTool


def _cue_text(cue: dict[str, Any]) -> str:
    return " ".join(str(cue.get("text") or "").split())


def _speaker(cue: dict[str, Any]) -> str:
    return str(cue.get("speaker") or "speaker")


def _format_range(start_ms: int, end_ms: int) -> str:
    return f"{start_ms / 1000:.2f}-{end_ms / 1000:.2f}s"


def _pack_cues(cues: list[dict[str, Any]], gap_ms: int = 500) -> list[dict[str, Any]]:
    packed: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for cue in sorted(cues, key=lambda item: int(item.get("start_ms") or 0)):
        text = _cue_text(cue)
        if not text:
            continue
        start_ms = int(cue.get("start_ms") or 0)
        end_ms = int(cue.get("end_ms") or start_ms)
        speaker = _speaker(cue)
        should_start = (
            current is None
            or speaker != current["speaker"]
            or start_ms - int(current["end_ms"]) >= gap_ms
        )
        if should_start:
            current = {
                "start_ms": start_ms,
                "end_ms": end_ms,
                "speaker": speaker,
                "texts": [text],
                "cue_ids": [cue.get("id")],
            }
            packed.append(current)
        else:
            current["end_ms"] = max(int(current["end_ms"]), end_ms)
            current["texts"].append(text)
            current["cue_ids"].append(cue.get("id"))
    return packed


def _packed_markdown(project_id: str, phrases: list[dict[str, Any]]) -> str:
    lines = [
        f"# Packed Transcript: {project_id}",
        "",
        "The agent should use this as the compact editing surface. Keep cuts near phrase edges when possible.",
        "",
    ]
    if not phrases:
        lines.append("No transcript or subtitle cues are currently available.")
        return "\n".join(lines)

    for index, phrase in enumerate(phrases, start=1):
        text = " ".join(phrase["texts"])
        lines.append(
            f"{index}. [{_format_range(int(phrase['start_ms']), int(phrase['end_ms']))}] "
            f"{phrase['speaker']}: {text}"
        )
    return "\n".join(lines) + "\n"


def _artifact_path(context: AgentToolContext, filename: str) -> Path:
    edit_dir = Path(context.project_dir) / "edit"
    edit_dir.mkdir(parents=True, exist_ok=True)
    return edit_dir / filename


def build_transcript_tools(context: AgentToolContext) -> list[AgentTool]:
    @tool("build_packed_transcript")
    async def build_packed_transcript(gap_ms: int = 500, limit: int = 200) -> dict:
        """把现有字幕/转写压缩成 phrase-level markdown，供 Agent 自主阅读和粗剪决策。"""
        cues = context.subtitle_cues()
        phrases = _pack_cues(cues, gap_ms=max(100, min(5000, int(gap_ms))))
        path = _artifact_path(context, "takes_packed.md")
        path.write_text(_packed_markdown(context.project_id, phrases), encoding="utf-8")
        preview = [
            {
                "start_ms": int(item["start_ms"]),
                "end_ms": int(item["end_ms"]),
                "speaker": item["speaker"],
                "text": " ".join(item["texts"])[:240],
                "cue_ids": [cue_id for cue_id in item["cue_ids"] if cue_id],
            }
            for item in phrases[:limit]
        ]
        return {
            "ok": True,
            "artifact_type": "packed_transcript",
            "artifact_path": str(path),
            "phrase_count": len(phrases),
            "source": "timeline_subtitles",
            "phrases": preview,
            "warning": None if phrases else "No subtitle cues are available to pack.",
        }

    @tool("find_transcript_gaps")
    async def find_transcript_gaps(min_gap_ms: int = 500, limit: int = 80) -> dict:
        """根据字幕 cue 间隔找停顿候选区间。用于粗剪前判断可删除停顿，而不是直接替代音频静音检测。"""
        cues = sorted(context.subtitle_cues(), key=lambda cue: int(cue.get("start_ms") or 0))
        gaps: list[dict[str, int]] = []
        for previous, current in pairwise(cues):
            start_ms = int(previous.get("end_ms") or 0)
            end_ms = int(current.get("start_ms") or 0)
            if end_ms - start_ms >= int(min_gap_ms):
                gaps.append({"start_ms": start_ms, "end_ms": end_ms, "duration_ms": end_ms - start_ms})
        return {
            "ok": True,
            "source": "timeline_subtitles",
            "min_gap_ms": min_gap_ms,
            "gap_count": len(gaps),
            "gaps": gaps[:limit],
        }

    return [build_packed_transcript, find_transcript_gaps]
