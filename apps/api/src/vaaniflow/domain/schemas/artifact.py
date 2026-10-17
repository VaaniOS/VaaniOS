from datetime import datetime
from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.audio import AudioMetadata
from vaaniflow.domain.schemas.common import DomainSchema


class AudioArtifact(DomainSchema):
    """
    Domain representation of an audio artifact.

    The artifact identifies an audio object and describes where its bytes
    are stored. The actual audio bytes are owned by the infrastructure
    storage layer and are never embedded in the domain model.
    """

    artifact_id: UUID

    storage_ref: str = Field(min_length=1)

    metadata: AudioMetadata

    created_at: datetime 