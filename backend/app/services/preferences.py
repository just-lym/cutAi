from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EditPlan, Project, UserPreference


def _mode_value(value: Any) -> str:
    return str(value.value) if hasattr(value, "value") else str(value)


def _increment(counts: dict[str, int], operation: dict[str, Any]) -> None:
    operation_type = str(operation.get("type") or "UNKNOWN")
    counts[operation_type] = int(counts.get(operation_type, 0)) + 1


def _range_duration(operation: dict[str, Any]) -> int | None:
    start = operation.get("start_ms", operation.get("timeline_start_ms"))
    end = operation.get("end_ms", operation.get("timeline_end_ms"))
    try:
        duration = int(end) - int(start)
    except (TypeError, ValueError):
        return None
    return duration if duration > 0 else None


async def get_preference_profile(
    db: AsyncSession,
    owner_id: str,
    video_type: str,
) -> dict[str, Any]:
    result = await db.execute(
        select(UserPreference).where(
            UserPreference.owner_id == owner_id,
            UserPreference.video_type == video_type,
        )
    )
    preference = result.scalar_one_or_none()
    if preference is None:
        return {"sample_count": 0, "confidence": 0.0}
    return {
        **dict(preference.profile or {}),
        "sample_count": preference.sample_count,
        "confidence": round(min(1.0, preference.sample_count / 20), 3),
    }


async def learn_from_approval(
    db: AsyncSession,
    project: Project,
    plan: EditPlan,
    approved_indices: set[int],
    rejected_indices: set[int],
    feedback_note: str | None = None,
) -> dict[str, Any]:
    result = await db.execute(
        select(UserPreference).where(
            UserPreference.owner_id == project.owner_id,
            UserPreference.video_type == _mode_value(project.video_type),
        )
    )
    preference = result.scalar_one_or_none()
    if preference is None:
        preference = UserPreference(
            owner_id=project.owner_id,
            video_type=_mode_value(project.video_type),
            profile={},
        )
        db.add(preference)

    profile = dict(preference.profile or {})
    accepted_counts = dict(profile.get("accepted_operations") or {})
    rejected_counts = dict(profile.get("rejected_operations") or {})
    accepted_durations = list(profile.get("accepted_range_durations_ms") or [])
    rejected_durations = list(profile.get("rejected_range_durations_ms") or [])
    operations = list(plan.operations or [])
    for index in approved_indices:
        if 0 <= index < len(operations):
            _increment(accepted_counts, operations[index])
            duration = _range_duration(operations[index])
            if duration:
                accepted_durations.append(duration)
    for index in rejected_indices:
        if 0 <= index < len(operations):
            _increment(rejected_counts, operations[index])
            duration = _range_duration(operations[index])
            if duration:
                rejected_durations.append(duration)

    notes = list(profile.get("feedback_notes") or [])
    if feedback_note and feedback_note.strip():
        notes.append(feedback_note.strip()[:500])
    accepted_total = sum(accepted_counts.values())
    rejected_total = sum(rejected_counts.values())
    sample_count = accepted_total + rejected_total
    profile = {
        "accepted_operations": accepted_counts,
        "rejected_operations": rejected_counts,
        "approval_rate": round(accepted_total / sample_count, 3) if sample_count else None,
        "accepted_range_durations_ms": accepted_durations[-50:],
        "rejected_range_durations_ms": rejected_durations[-50:],
        "feedback_notes": notes[-20:],
    }
    preference.profile = profile
    preference.sample_count = sample_count
    await db.flush()
    return {**profile, "sample_count": sample_count, "confidence": round(min(1.0, sample_count / 20), 3)}
