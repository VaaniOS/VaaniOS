"""
HTTP authentication boundary (ADR-022).

Callers authenticate with ``Authorization: Bearer <token>``. An IdentityProvider
maps the token to a Principal; the default provider reads an explicit token map
from ``VAANIFLOW_API_TOKENS``. Unset means no principals: every protected route
answers 401. No header other than Authorization is read, and no token format
asserts a role or identity by itself.

This is a deliberately small sandbox credential store (static tokens, no expiry
or rotation). Other adapters (e.g. Telegram) must map their users to Principals
through their own explicit, configured IdentityProvider — never by assertion.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Callable, Mapping
from typing import Annotated, Protocol

from fastapi import Depends, HTTPException, Request, status

from vaaniflow.config.principals import parse_principal_map
from vaaniflow.domain.models.principal import (
    AuthorizationError,
    Permission,
    Principal,
    require_permission,
)

TOKENS_ENV = "VAANIFLOW_API_TOKENS"
MIN_TOKEN_LENGTH = 16


class IdentityProvider(Protocol):
    def authenticate(self, credential: str) -> Principal | None: ...


class StaticTokenIdentityProvider:
    """Maps opaque bearer tokens to principals. Unknown tokens authenticate no one."""

    def __init__(self, principals: Mapping[str, Principal] | None = None) -> None:
        self._principals = dict(principals or {})

    def authenticate(self, credential: str) -> Principal | None:
        found: Principal | None = None
        for token, principal in self._principals.items():
            if hmac.compare_digest(token.encode(), credential.encode()):
                found = principal
        return found

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> StaticTokenIdentityProvider:
        """
        ``VAANIFLOW_API_TOKENS`` = ``{"<token>": {"actor_id": "<uuid>", "name": "...",
        "roles": ["OWNER", ...]}}``. Unset → no tokens. A malformed value raises:
        misconfigured authentication must not silently open or close.
        """
        raw = (environ if environ is not None else os.environ).get(TOKENS_ENV, "").strip()
        if not raw:
            return cls()
        principals = parse_principal_map(
            raw, source=TOKENS_ENV, authentication_method="bearer-token"
        )
        if any(len(token) < MIN_TOKEN_LENGTH for token in principals):
            raise ValueError(
                f"{TOKENS_ENV} tokens must be at least {MIN_TOKEN_LENGTH} characters long."
            )
        return cls(principals)


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _http_error(error: AuthorizationError) -> HTTPException:
    if error.code == "UNAUTHENTICATED":
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTHENTICATION_REQUIRED", "message": error.message},
            headers={"WWW-Authenticate": "Bearer"},
        )
    if error.code == "FORBIDDEN":
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": error.message},
        )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": error.code, "message": error.message},
    )


def authorization_http_error(error: AuthorizationError) -> HTTPException:
    """HTTP form of an AuthorizationError: 401, 403, or 409 for run-state refusals."""
    return _http_error(error)


def authenticate(request: Request) -> Principal:
    """FastAPI dependency: the principal behind the bearer token, or 401."""
    from vaaniflow.api.dependencies import get_container  # avoid an import cycle

    token = _bearer_token(request)
    if token is None:
        raise _http_error(AuthorizationError("UNAUTHENTICATED", "No bearer token presented."))
    principal = get_container().identity_provider.authenticate(token)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CREDENTIALS", "message": "Invalid bearer token."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


def require(permission: Permission) -> Callable[..., Principal]:
    """FastAPI dependency: an authenticated principal holding ``permission`` (401/403)."""

    def dependency(principal: Annotated[Principal, Depends(authenticate)]) -> Principal:
        try:
            return require_permission(principal, permission)
        except AuthorizationError as error:
            raise _http_error(error) from error

    return dependency


AuthenticatedDep = Annotated[Principal, Depends(authenticate)]
InstructorDep = Annotated[Principal, Depends(require(Permission.SUBMIT_INSTRUCTION))]
ApproverDep = Annotated[Principal, Depends(require(Permission.APPROVE))]
ConfirmerDep = Annotated[Principal, Depends(require(Permission.CONFIRM))]
ResolverDep = Annotated[Principal, Depends(require(Permission.RESOLVE_UNKNOWN))]
EscalatorDep = Annotated[Principal, Depends(require(Permission.CREATE_HANDOFF))]
AuditorDep = Annotated[Principal, Depends(require(Permission.READ_AUDIT))]
