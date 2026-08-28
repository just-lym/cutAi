from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CloudAPIUsage


class BudgetExceededError(RuntimeError):
    pass


@dataclass(frozen=True)
class TokenPricing:
    input: float
    output: float


PRICING = {
    "qwen-max": TokenPricing(input=0.02, output=0.06),
    "qwen-plus": TokenPricing(input=0.004, output=0.012),
    "qwen-turbo": TokenPricing(input=0.0005, output=0.002),
    "text-embedding-v3": TokenPricing(input=0.0007, output=0.0),
    "paraformer-v2": 3.6,
}


def calculate_cost(
    service: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    audio_duration_ms: int = 0,
) -> float:
    pricing = PRICING.get(service)
    if pricing is None:
        return 0.0
    if isinstance(pricing, TokenPricing):
        return (input_tokens / 1_000_000) * pricing.input + (output_tokens / 1_000_000) * pricing.output
    return (audio_duration_ms / 3_600_000) * pricing


async def record_usage(
    db: AsyncSession,
    provider: str,
    service: str,
    project_id: UUID | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    audio_duration_ms: int = 0,
    request_id: str | None = None,
) -> CloudAPIUsage:
    usage = CloudAPIUsage(
        project_id=project_id,
        provider=provider,
        service=service,
        request_id=request_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        audio_duration_ms=audio_duration_ms,
        cost_yuan=calculate_cost(service, input_tokens, output_tokens, audio_duration_ms),
    )
    db.add(usage)
    await db.flush()
    return usage
