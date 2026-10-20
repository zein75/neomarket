from dataclasses import dataclass
from uuid import UUID

from src.models.seller import Seller
from src.models.seller_membership import SellerMembership
from src.models.seller_user import SellerUser


@dataclass(frozen=True)
class SellerPrincipal:
    """Authenticated user and the organization context used for tenant scoping."""

    organization: Seller
    user: SellerUser
    membership: SellerMembership

    @property
    def id(self) -> UUID:
        return self.organization.id

    @property
    def user_id(self) -> UUID:
        return self.user.id

    @property
    def role(self) -> str:
        return self.membership.role

    @property
    def email(self) -> str:
        return self.user.email

    @property
    def company_name(self) -> str:
        return self.organization.company_name

    @property
    def is_active(self) -> bool:
        return self.organization.is_active and self.user.is_active and self.membership.active

    @property
    def account_status(self) -> str:
        return self.organization.account_status

    @property
    def email_verified_at(self):
        return self.user.email_verified_at

    @property
    def session_version(self) -> int:
        return self.user.session_version
