from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import settings


@dataclass
class AgentToolContext:
    project_id: str
    project_dir: str
    timeline_version: int | None
    timeline: dict[str, Any]
    assets: list[dict[str, Any]]
    preferences: dict[str, Any] | None = None
    selection: dict[str, Any] | None = None

    @property
    def output_dir(self) -> Path:
        path = Path(self.project_dir) / "agent_outputs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def asset_path(self, asset: dict[str, Any]) -> Path:
        return settings.data_root / str(asset.get("file_path"))

    def effective_duration_ms(self) -> int:
        timeline_duration = int(self.timeline.get("duration_ms") or 0)
        asset_duration = max((int(asset.get("duration_ms") or 0) for asset in self.assets), default=0)
        return max(timeline_duration, asset_duration)

    def tracks(self) -> list[dict[str, Any]]:
        return list(self.timeline.get("tracks") or [])

    def subtitle_cues(self) -> list[dict[str, Any]]:
        for track in self.tracks():
            if track.get("id") == "subtitles" or track.get("type") == "SUBTITLE":
                return list(track.get("cues") or [])
        return []

    def referenced_asset_ids(self) -> set[str]:
        ids: set[str] = set()
        for track in self.tracks():
            for clip in track.get("clips") or []:
                asset_id = clip.get("asset_id")
                if asset_id:
                    ids.add(str(asset_id))
        return ids

    def find_asset(self, asset_id: str | None = None, media_only: bool = False) -> dict[str, Any] | None:
        if not asset_id:
            asset_id = str((self.selection or {}).get("asset_id") or "") or None
        if asset_id:
            return next((asset for asset in self.assets if str(asset.get("id")) == str(asset_id)), None)

        referenced_ids = self.referenced_asset_ids()
        for asset in self.assets:
            if str(asset.get("id")) not in referenced_ids:
                continue
            if asset.get("processing_status") != "COMPLETED":
                continue
            if media_only and asset.get("type") not in {"VIDEO", "AUDIO"}:
                continue
            return asset

        return next(
            (
                asset
                for asset in self.assets
                if asset.get("processing_status") == "COMPLETED"
                and (not media_only or asset.get("type") in {"VIDEO", "AUDIO"})
            ),
            None,
        )


def diagnosis_summary(asset: dict[str, Any]) -> dict[str, Any] | None:
    diagnosis = (asset.get("metadata") or {}).get("diagnosis")
    if not isinstance(diagnosis, dict):
        return None
    beats = diagnosis.get("audio_beats") or {}
    visual = diagnosis.get("visual") or {}
    scenes = diagnosis.get("scenes") or []
    return {
        "status": diagnosis.get("status"),
        "scene_count": len(scenes),
        "bpm": beats.get("bpm"),
        "beat_confidence": beats.get("confidence"),
        "visual_summary": visual.get("summary"),
        "quality_issues": list(visual.get("quality_issues") or [])[:8],
        "strong_moments": list(visual.get("strong_moments") or [])[:8],
        "editing_suggestions": list(visual.get("editing_suggestions") or [])[:8],
        "issues": list(diagnosis.get("issues") or [])[:8],
    }


def asset_summary(context: AgentToolContext, asset: dict[str, Any], include_path: bool = False) -> dict[str, Any]:
    summary = {
        "id": asset.get("id"),
        "name": asset.get("original_name"),
        "type": asset.get("type"),
        "duration_ms": asset.get("duration_ms"),
        "width": asset.get("width"),
        "height": asset.get("height"),
        "frame_rate": asset.get("frame_rate"),
        "processing_status": asset.get("processing_status"),
        "diagnosis": diagnosis_summary(asset),
    }
    if include_path:
        summary["file_path"] = str(context.asset_path(asset))
    return summary
