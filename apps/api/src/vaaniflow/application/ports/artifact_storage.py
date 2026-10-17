from __future__ import annotations

from io import BufferedIOBase
from typing import Protocol

from vaaniflow.domain.schemas.artifact import AudioArtifact


class ArtifactStorageError(Exception):
    """Base error for artifact storage failures."""


class ArtifactNotFoundError(ArtifactStorageError):
    """Raised when a requested artifact does not exist."""


class ArtifactStorage(Protocol):
    """
    Port for persistent storage of audio artifacts.

    Implementations own the physical storage mechanism. Callers only know
    about opaque storage references and artifact metadata.
    """

    def store(
        self,
        *,
        artifact: AudioArtifact,
        data: BufferedIOBase,
    ) -> None:
        """
        Persist an audio artifact.

        The artifact's storage_ref identifies the destination.
        """

    def open(
        self,
        *,
        storage_ref: str,
    ) -> BufferedIOBase:
        """
        Open an existing artifact for reading.

        Raises:
            ArtifactNotFoundError: if the reference does not exist.
            ArtifactStorageError: for other storage failures.
        """

    def delete(
        self,
        *,
        storage_ref: str,
    ) -> None:
        """
        Delete an artifact.

        Raises:
            ArtifactNotFoundError: if the reference does not exist.
            ArtifactStorageError: for other storage failures.
        """