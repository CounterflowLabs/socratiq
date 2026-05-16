"""Activation-code redemption + subscription-status endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.db.models.activation_code import ActivationCode
from app.db.models.user import User
from app.models.activation import (
    RedeemRequest,
    RedeemResponse,
    SubscriptionStatus,
)
from app.services.activation import (
    CodeAlreadyRedeemed,
    CodeNotFound,
    CodeRevoked,
    has_active_subscription,
    redeem_code,
)

router = APIRouter(prefix="/api/v1/activation", tags=["activation"])


@router.get("/status", response_model=SubscriptionStatus)
async def status_(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionStatus:
    tier: str | None = None
    if user.activation_code_id is not None:
        code = await db.get(ActivationCode, user.activation_code_id)
        if code is not None:
            tier = code.tier
    return SubscriptionStatus(
        has_active_subscription=has_active_subscription(user),
        subscription_until=user.subscription_until,
        monthly_usd_cap=float(user.monthly_usd_cap)
        if user.monthly_usd_cap is not None
        else None,
        tier=tier,
    )


@router.post("/redeem", response_model=RedeemResponse)
async def redeem(
    req: RedeemRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RedeemResponse:
    try:
        result = await redeem_code(db, code_value=req.code, user=user)
    except CodeNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "code_not_found", "message": "激活码不存在"},
        )
    except CodeAlreadyRedeemed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "code_already_used", "message": "激活码已被使用"},
        )
    except CodeRevoked:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"code": "code_revoked", "message": "激活码已作废"},
        )

    return RedeemResponse(
        code=result.code.code,
        tier=result.code.tier,
        subscription_until=result.subscription_until,
        monthly_usd_cap=result.monthly_usd_cap,
    )
