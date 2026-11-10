from enum import StrEnum
from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.common import DomainSchema


class Role(StrEnum):
    USER = "user"
    OPERATOR = "operator"
    ADMIN = "admin"


class Principal(DomainSchema):
    """
    Authenticated identity representing the actor initiating an API request.
    """

    principal_id: UUID
    username: str = ""
    role: Role = Role.USER
    is_authenticated: bool = True
    metadata: dict[str, str] = Field(default_factory=dict)
