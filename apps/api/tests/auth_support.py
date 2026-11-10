"""Test principals and bearer tokens for the authentication boundary (ADR-022)."""

from __future__ import annotations

from uuid import UUID

from vaaniflow.api.auth import StaticTokenIdentityProvider
from vaaniflow.domain.models.principal import Principal, Role


def _principal(n: int, name: str, *roles: Role) -> Principal:
    return Principal(
        principal_id=UUID(f"00000000-0000-4000-8000-0000000000a{n}"),
        display_name=name,
        roles=list(roles),
        authentication_method="bearer-token",
    )


OWNER = _principal(1, "test owner", Role.OWNER)
REQUESTER = _principal(2, "test requester", Role.REQUESTER)
OPERATOR = _principal(3, "test operator", Role.OPERATOR)
AUDITOR = _principal(4, "test auditor", Role.AUDITOR)
NO_ROLES = _principal(5, "test no-roles user")
# Holds every role: for tests that exercise flows rather than role separation.
STAFF = _principal(6, "test staff", Role.OWNER, Role.REQUESTER, Role.OPERATOR, Role.AUDITOR)
OTHER_REQUESTER = _principal(7, "other requester", Role.REQUESTER)

TOKENS = {
    "token-owner-0000000001": OWNER,
    "token-requester-000002": REQUESTER,
    "token-operator-0000003": OPERATOR,
    "token-auditor-00000004": AUDITOR,
    "token-noroles-00000005": NO_ROLES,
    "token-staff-0000000006": STAFF,
    "token-other-req-000007": OTHER_REQUESTER,
}
_BY_PRINCIPAL = {p.principal_id: token for token, p in TOKENS.items()}


def provider() -> StaticTokenIdentityProvider:
    return StaticTokenIdentityProvider(TOKENS)


def auth(principal: Principal = STAFF) -> dict[str, str]:
    return {"Authorization": f"Bearer {_BY_PRINCIPAL[principal.principal_id]}"}
