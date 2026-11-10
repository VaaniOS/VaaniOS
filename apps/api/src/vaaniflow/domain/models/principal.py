"""
Authenticated identity and authorization rules (ADR-022).

A ``Principal`` only ever comes from an identity provider that verified a
credential (see ``vaaniflow.api.auth``), or is the explicitly labelled synthetic
evaluation actor. Request bodies, headers, callback payloads and run fields never
create one. Authorization is a separate decision per ``Permission``.
"""

from enum import StrEnum
from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.common import DomainSchema


class Role(StrEnum):
    OWNER = "OWNER"  # approves or rejects consequential business writes
    REQUESTER = "REQUESTER"  # submits instructions and confirms what they meant
    OPERATOR = "OPERATOR"  # settles UNKNOWN outcomes, escalates, may re-instruct any run
    AUDITOR = "AUDITOR"  # reads run audit trails


class Permission(StrEnum):
    SUBMIT_INSTRUCTION = "SUBMIT_INSTRUCTION"
    APPROVE = "APPROVE"
    CONFIRM = "CONFIRM"
    RESOLVE_UNKNOWN = "RESOLVE_UNKNOWN"
    CREATE_HANDOFF = "CREATE_HANDOFF"
    READ_AUDIT = "READ_AUDIT"


PERMISSION_ROLES: dict[Permission, frozenset[Role]] = {
    Permission.SUBMIT_INSTRUCTION: frozenset({Role.REQUESTER, Role.OWNER, Role.OPERATOR}),
    Permission.APPROVE: frozenset({Role.OWNER}),
    Permission.CONFIRM: frozenset({Role.REQUESTER, Role.OWNER}),
    Permission.RESOLVE_UNKNOWN: frozenset({Role.OPERATOR}),
    Permission.CREATE_HANDOFF: frozenset({Role.OPERATOR}),
    Permission.READ_AUDIT: frozenset({Role.AUDITOR, Role.OPERATOR, Role.OWNER}),
}


class Principal(DomainSchema):
    """An identity established by verifying a credential, with explicit roles."""

    principal_id: UUID
    display_name: str = Field(min_length=1)
    roles: list[Role] = Field(default_factory=list)
    # How the identity was established, e.g. "bearer-token" or "synthetic-evaluation".
    authentication_method: str = Field(min_length=1)
    # True only for the evaluation harness's actor; never an external caller.
    synthetic: bool = False

    def has_role(self, role: Role) -> bool:
        return role in self.roles

    def may(self, permission: Permission) -> bool:
        return bool(set(self.roles) & PERMISSION_ROLES[permission])


class AuthorizationError(Exception):
    """Raised when no principal is present (UNAUTHENTICATED) or it lacks a permission."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def require_permission(principal: Principal | None, permission: Permission) -> Principal:
    """The principal, if it holds ``permission``; otherwise AuthorizationError."""
    if principal is None:
        raise AuthorizationError(
            "UNAUTHENTICATED", f"{permission.value} requires an authenticated principal."
        )
    if not principal.may(permission):
        raise AuthorizationError(
            "FORBIDDEN",
            f"Roles {[r.value for r in principal.roles]} do not grant {permission.value}.",
        )
    return principal


# The only principal not backed by a credential: the sandbox harness confirms and
# approves its own isolated scenarios with it. It is labelled synthetic everywhere
# it is recorded and is never produced by an identity provider.
SYNTHETIC_EVALUATION_OWNER = Principal(
    principal_id=UUID("00000000-0000-4000-8000-0000000000e1"),
    display_name="synthetic evaluation owner",
    roles=[Role.OWNER, Role.REQUESTER],
    authentication_method="synthetic-evaluation",
    synthetic=True,
)
