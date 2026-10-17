from __future__ import annotations

from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.audio import AudioMetadata
from vaaniflow.domain.schemas.common import DomainSchema


class AudioPreprocessingInput(DomainSchema):
    """
    Provider-neutral input describing the audio artifact to preprocess.

    The audio bytes are supplied separately by the application execution
    layer. This schema carries only artifact identity and metadata.
    """

    artifact_id: UUID
    storage_ref: str = Field(min_length=1)
    metadata: AudioMetadata


class AudioPreprocessingResult(DomainSchema):
    """
    Provider-neutral result produced by an audio preprocessing stage.

    The resulting audio bytes are stored separately by the application
    storage layer. This schema identifies the resulting artifact and
    describes its resulting metadata.
    """

    artifact_id: UUID
    storage_ref: str = Field(min_length=1)
    metadata: AudioMetadata