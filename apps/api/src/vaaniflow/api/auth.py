from typing import Annotated
from uuid import NAMESPACE_DNS, UUID, uuid5

from fastapi import Depends, Header, HTTPException, status

from vaaniflow.domain.models.principal import Principal, Role


def _parse_principal_id(token: str) -> tuple[UUID, Role]:
    token = token.strip()
    role = Role.USER
    if token.startswith("operator:"):
        role = Role.OPERATOR
        token = token[len("operator:") :]
    elif token.startswith("admin:"):
        role = Role.ADMIN
        token = token[len("admin:") :]

    try:
        return UUID(token), role
    except ValueError:
        # If token is a named subject (e.g. 'operator-1'), generate a deterministic UUID
        return uuid5(NAMESPACE_DNS, token), role


def get_optional_principal(
    authorization: str | None = Header(default=None),
    x_principal_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
) -> Principal | None:
    """
    Extract an optional authenticated principal from Authorization or identity headers.
    Returns None when the request is anonymous.
    """
    raw_token = None
    if authorization:
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw_token = parts[1]
        elif len(parts) == 1:
            raw_token = parts[0]
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "INVALID_CREDENTIALS",
                    "message": "Malformed Authorization header.",
                },
            )
    elif x_principal_id:
        raw_token = x_principal_id
    elif x_user_id:
        raw_token = x_user_id

    if not raw_token:
        return None

    try:
        principal_id, role = _parse_principal_id(raw_token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CREDENTIALS", "message": "Invalid authentication token."},
        ) from exc

    if x_role:
        try:
            role = Role(x_role.lower())
        except ValueError:
            pass

    return Principal(
        principal_id=principal_id,
        role=role,
        is_authenticated=True,
    )


PrincipalDep = Annotated[Principal | None, Depends(get_optional_principal)]


def require_authenticated_principal(
    principal: Principal | None = None,
) -> Principal:
    """
    Ensure an authenticated principal exists, otherwise raise 401.
    """
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "AUTHENTICATION_REQUIRED",
                "message": "Authentication required for this operation.",
            },
        )
    return principal
