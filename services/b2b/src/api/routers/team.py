from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, require_seller_permission
from src.core.identity import SellerPrincipal
from src.core.redis import get_redis
from src.models.seller import Seller
from src.models.seller_membership import SellerRole
from src.models.seller_membership_audit import SellerMembershipAudit
from src.repositories.seller_repo import SellerRepository
from src.schemas.seller import (
    SellerInviteAccept,
    SellerInviteAcceptResponse,
    SellerInviteCreate,
    SellerInviteResponse,
    SellerMemberResponse,
    SellerMemberRoleUpdate,
    SellerMembershipRevoke,
)
from src.services.auth_service import AuthService
from src.services.email_delivery import (
    require_email_delivery_configured,
    send_seller_invitation_email,
)
from src.services.login_rate_limiter import check_login_rate_limit

router = APIRouter(prefix="/team", tags=["seller-team"])


@router.get("/members", response_model=list[SellerMemberResponse])
async def list_members(
    current_seller: Seller | SellerPrincipal = Depends(
        require_seller_permission("team.manage")
    ),
    db: AsyncSession = Depends(get_db),
) -> list[SellerMemberResponse]:
    rows = await SellerRepository(db).list_members(current_seller.id)
    return [
        SellerMemberResponse(
            id=membership.user_id,
            email=user.email,
            role=membership.role,
            active=membership.active,
            created_at=membership.created_at,
            revision=membership.revision,
        )
        for membership, user in rows
    ]


@router.patch("/members/{user_id}", response_model=SellerMemberResponse)
async def update_member_role(
    user_id: UUID,
    data: SellerMemberRoleUpdate,
    response: Response,
    if_match: str = Header(..., alias="If-Match"),
    current_seller: Seller | SellerPrincipal = Depends(
        require_seller_permission("team.manage")
    ),
    db: AsyncSession = Depends(get_db),
) -> SellerMemberResponse:
    expected_revision = _parse_if_match_revision(if_match)
    actor_user_id = (
        current_seller.user_id
        if isinstance(current_seller, SellerPrincipal)
        else current_seller.id
    )
    if actor_user_id == user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "SELF_MEMBERSHIP_CHANGE", "message": "Owners cannot change their own membership"},
        )

    repo = SellerRepository(db)
    membership = await repo.get_membership_for_update(current_seller.id, user_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Seller member not found")
    if membership.role == SellerRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "OWNER_MEMBERSHIP_PROTECTED", "message": "Owner transfer must use its dedicated workflow"},
        )
    if membership.revision != expected_revision:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail={"code": "STALE_REVISION", "message": "Membership has changed; reload before retrying"},
        )

    previous_role = membership.role
    new_role = data.role.value
    if previous_role != new_role:
        membership.role = new_role
        membership.revision += 1
        if not await repo.revoke_user_sessions(user_id):
            raise HTTPException(status_code=404, detail="Seller member not found")
        db.add(
            SellerMembershipAudit(
                seller_id=current_seller.id,
                actor_user_id=actor_user_id,
                target_user_id=user_id,
                action="ROLE_CHANGED",
                previous_role=previous_role,
                new_role=new_role,
                reason=data.reason,
            )
        )
        await db.flush()
    user = await repo.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Seller member not found")
    response.headers["ETag"] = f'"{membership.revision}"'
    result = SellerMemberResponse(
        id=membership.user_id,
        email=user.email,
        role=membership.role,
        active=membership.active,
        created_at=membership.created_at,
        revision=membership.revision,
    )
    await db.commit()
    return result


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_member(
    user_id: UUID,
    data: SellerMembershipRevoke,
    if_match: str = Header(..., alias="If-Match"),
    current_seller: Seller | SellerPrincipal = Depends(
        require_seller_permission("team.manage")
    ),
    db: AsyncSession = Depends(get_db),
) -> Response:
    expected_revision = _parse_if_match_revision(if_match)
    actor_user_id = (
        current_seller.user_id
        if isinstance(current_seller, SellerPrincipal)
        else current_seller.id
    )
    if actor_user_id == user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "SELF_MEMBERSHIP_CHANGE", "message": "Owners cannot revoke their own membership"},
        )

    repo = SellerRepository(db)
    membership = await repo.get_membership_for_update(current_seller.id, user_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Seller member not found")
    if membership.role == SellerRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "OWNER_MEMBERSHIP_PROTECTED", "message": "Owner transfer must use its dedicated workflow"},
        )
    if membership.revision != expected_revision:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail={"code": "STALE_REVISION", "message": "Membership has changed; reload before retrying"},
        )

    previous_role = membership.role
    membership.active = False
    membership.revision += 1
    if not await repo.revoke_user_sessions(user_id):
        raise HTTPException(status_code=404, detail="Seller member not found")
    db.add(
        SellerMembershipAudit(
            seller_id=current_seller.id,
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            action="MEMBERSHIP_REVOKED",
            previous_role=previous_role,
            new_role=None,
            reason=data.reason,
        )
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _parse_if_match_revision(value: str) -> int:
    candidate = value.strip().strip('"')
    try:
        revision = int(candidate)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REVISION", "message": "If-Match must contain an integer membership revision"},
        ) from exc
    if revision < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REVISION", "message": "Revision must be positive"},
        )
    return revision


@router.post(
    "/invitations",
    response_model=SellerInviteResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "User is already a member"}, 429: {"description": "Invite rate limit exceeded"}, 503: {"description": "Email delivery is unavailable"}},
)
async def create_invitation(
    data: SellerInviteCreate,
    request: Request,
    current_seller: Seller | SellerPrincipal = Depends(
        require_seller_permission("team.manage")
    ),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> SellerInviteResponse:
    require_email_delivery_configured()
    client_ip = request.client.host if request.client else "unknown"
    email = str(data.email).strip().lower()
    await check_login_rate_limit(redis, email=email, client_ip=client_ip, action="invite")
    invited_by_user_id = (
        current_seller.user_id
        if isinstance(current_seller, SellerPrincipal)
        else current_seller.id
    )
    service = AuthService(db)
    try:
        invite, token = await service.issue_seller_invite(
            seller_id=current_seller.id,
            invited_by_user_id=invited_by_user_id,
            email=email,
            role=data.role,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An invitation for this email already exists",
        ) from exc
    await send_seller_invitation_email(
        email,
        token,
        company_name=current_seller.company_name,
        role=invite.role,
        expires_at=invite.expires_at,
    )
    return SellerInviteResponse(
        id=invite.id,
        role=invite.role,
        expires_at=invite.expires_at,
    )


@router.post(
    "/invitations/accept",
    response_model=SellerInviteAcceptResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "Invitation invalid, expired, revoked, or already used"},
        401: {"description": "Existing account credentials are invalid"},
    },
)
async def accept_invitation(
    data: SellerInviteAccept,
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> SellerInviteAcceptResponse:
    client_ip = request.client.host if request.client else "unknown"
    email = str(data.email).strip().lower()
    await check_login_rate_limit(redis, email=email, client_ip=client_ip, action="invite")
    service = AuthService(db)
    try:
        accepted_email, seller_id, role = await service.accept_seller_invite(
            token=data.token,
            email=email,
            password=data.password,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account or membership already exists",
        ) from exc
    return SellerInviteAcceptResponse(
        status="ACCEPTED",
        email=accepted_email,
        seller_id=seller_id,
        role=role,
    )
