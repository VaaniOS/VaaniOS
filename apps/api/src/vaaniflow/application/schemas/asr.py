from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.audio import AudioMetadata
from vaaniflow.domain.schemas.common import DomainSchema


class ASRInput(DomainSchema):
    """
    Provider-neutral metadata describing an ASR request.

    Audio bytes are supplied separately by the application execution layer.
    """

    artifact_id: UUID
    metadata: AudioMetadata
    language_hint: str | None = Field(default=None, min_length=1)