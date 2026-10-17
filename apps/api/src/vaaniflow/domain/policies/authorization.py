from enum import StrEnum
from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.common import DomainSchema


class AuthorizationStatus(StrEnum):
    AUTHORIZED = "AUTHORIZED"
    DENIED = "DENIED"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"


class AuthorizationAction(StrEnum):
    READ = "READ"
    CREATE_DRAFT = "CREATE_DRAFT"
    MODIFY = "MODIFY"
    CANCEL = "CANCEL"
    DISPATCH = "DISPATCH"
    ISSUE_INVOICE = "ISSUE_INVOICE"
    SEND_NOTIFICATION = "SEND_NOTIFICATION"


class AuthorizationResult(DomainSchema):
    """
    Authorization result for a proposed business action.

    Authentication, authorization and human approval are deliberately
    represented as separate concepts.
    """

    authorization_id: UUID

    run_id: UUID

    action: AuthorizationAction

    status: AuthorizationStatus

    actor_id: UUID | None = None

    reason: str = Field(min_length=1)

    policy_version: str = Field(min_length=1)

    approval_required: bool = False
