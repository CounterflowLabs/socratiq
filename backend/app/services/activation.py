"""Activation-code generation and redemption logic for the closed-beta paywall."""

import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.activation_code import ActivationCode
from app.db.models.user import User


# Tier presets. Keep these in code so the CLI and runtime stay in sync; the
# values are denormalized onto each code at generation time so changes here
# don't retroactively alter already-issued codes.
TIERS: dict[str, dict[str, float | int]] = {
    "beta_30d": {"valid_days": 30, "monthly_usd_cap": 20.0},
    "beta_90d": {"valid_days": 90, "monthly_usd_cap": 20.0},
    "beta_pro_30d": {"valid_days": 30, "monthly_usd_cap": 60.0},
}

CODE_PREFIX = "SCQ"
_ALPHABET = string.ascii_uppercase + string.digits


class ActivationError(Exception):
    """Base class for activation-code errors."""


class CodeNotFound(ActivationError):
    pass


class CodeAlreadyRedeemed(ActivationError):
    pass


class CodeRevoked(ActivationError):
    pass


class UnknownTier(ActivationError):
    pass


@dataclass(slots=True)
class RedemptionResult:
    code: ActivationCode
    subscription_until: datetime
    monthly_usd_cap: float


def generate_code_string() -> str:
    """Produce a human-friendly random code like ``SCQ-AB12-CD34-EF56``."""
    groups = ["".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(3)]
    return f"{CODE_PREFIX}-" + "-".join(groups)


async def create_codes(
    db: AsyncSession,
    *,
    tier: str,
    count: int = 1,
    note: str | None = None,
) -> list[ActivationCode]:
    if tier not in TIERS:
        raise UnknownTier(f"Unknown tier: {tier}. Known: {list(TIERS)}")
    spec = TIERS[tier]
    out: list[ActivationCode] = []
    for _ in range(count):
        code = ActivationCode(
            code=generate_code_string(),
            tier=tier,
            valid_days=int(spec["valid_days"]),
            monthly_usd_cap=float(spec["monthly_usd_cap"]),
            note=note,
        )
        db.add(code)
        out.append(code)
    await db.flush()
    return out


async def redeem_code(
    db: AsyncSession, *, code_value: str, user: User
) -> RedemptionResult:
    """Redeem `code_value` for `user`, granting subscription + monthly cap.

    Raises an `ActivationError` subclass on validation failure; otherwise
    mutates the code and the user and returns the resulting state.
    """
    code_value = code_value.strip().upper()
    result = await db.execute(
        select(ActivationCode).where(ActivationCode.code == code_value)
    )
    code = result.scalar_one_or_none()
    if code is None:
        raise CodeNotFound("Activation code not found")
    if code.revoked_at is not None:
        raise CodeRevoked("Activation code has been revoked")
    if code.redeemed_by_user_id is not None:
        raise CodeAlreadyRedeemed("Activation code has already been used")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # Stack onto an existing entitlement if the user is still active; otherwise
    # start from now. This keeps buying two codes back-to-back fair.
    base = (
        user.subscription_until
        if user.subscription_until and user.subscription_until > now
        else now
    )
    new_expiry = base + timedelta(days=code.valid_days)

    code.redeemed_by_user_id = user.id
    code.redeemed_at = now

    user.activation_code_id = code.id
    user.subscription_until = new_expiry
    user.monthly_usd_cap = float(code.monthly_usd_cap)

    await db.flush()
    return RedemptionResult(
        code=code,
        subscription_until=new_expiry,
        monthly_usd_cap=float(code.monthly_usd_cap),
    )


def has_active_subscription(user: User) -> bool:
    if user.subscription_until is None:
        return False
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return user.subscription_until > now
