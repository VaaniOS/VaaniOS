from __future__ import annotations

from io import BufferedIOBase
from pathlib import Path, PurePosixPath

from vaaniflow.application.ports.artifact_storage import (
    ArtifactAlreadyExistsError,
    ArtifactNotFoundError,
    ArtifactStorage,
    ArtifactStorageError,
)
from vaaniflow.domain.schemas.artifact import AudioArtifact


class LocalArtifactStorage:
    """
    Filesystem-backed implementation of the ArtifactStorage port.

    Storage references must use the form:

        local://<relative/path>

    Example:

        local://audio/01JABC123.wav

    The reference is always resolved relative to the configured root
    directory. Path traversal outside the root is rejected.
    """

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def store(
        self,
        *,
        artifact: AudioArtifact,
        data: BufferedIOBase,
    ) -> None:
        path = self._resolve_storage_ref(artifact.storage_ref)

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # "xb" fails if the file exists: artifacts are write-once.
            with path.open("xb") as destination:
                while chunk := data.read(1024 * 1024):
                    destination.write(chunk)
        except FileExistsError as exc:
            raise ArtifactAlreadyExistsError(artifact.storage_ref) from exc
        except OSError as exc:
            raise ArtifactStorageError(f"Failed to store artifact: {artifact.storage_ref}") from exc

    def open(
        self,
        *,
        storage_ref: str,
    ) -> BufferedIOBase:
        path = self._resolve_storage_ref(storage_ref)

        if not path.exists():
            raise ArtifactNotFoundError(storage_ref)

        if not path.is_file():
            raise ArtifactStorageError(f"Artifact storage reference is not a file: {storage_ref}")

        try:
            return path.open("rb")
        except FileNotFoundError as exc:
            raise ArtifactNotFoundError(storage_ref) from exc
        except OSError as exc:
            raise ArtifactStorageError(f"Failed to open artifact: {storage_ref}") from exc

    def delete(
        self,
        *,
        storage_ref: str,
    ) -> None:
        path = self._resolve_storage_ref(storage_ref)

        if not path.exists():
            raise ArtifactNotFoundError(storage_ref)

        if not path.is_file():
            raise ArtifactStorageError(f"Artifact storage reference is not a file: {storage_ref}")

        try:
            path.unlink()
        except FileNotFoundError as exc:
            raise ArtifactNotFoundError(storage_ref) from exc
        except OSError as exc:
            raise ArtifactStorageError(f"Failed to delete artifact: {storage_ref}") from exc

    def _resolve_storage_ref(self, storage_ref: str) -> Path:
        """
        Resolve an opaque local storage reference to a filesystem path.

        Only local:// references are accepted.

        The resolved path must remain inside the configured storage root.
        """

        prefix = "local://"

        if not storage_ref.startswith(prefix):
            raise ArtifactStorageError(f"Unsupported artifact storage reference: {storage_ref}")

        relative_ref = storage_ref[len(prefix) :]

        if not relative_ref:
            raise ArtifactStorageError("Artifact storage reference cannot be empty.")

        relative_path = PurePosixPath(relative_ref)

        if relative_path.is_absolute():
            raise ArtifactStorageError(
                f"Artifact storage reference must be relative: {storage_ref}"
            )

        if ".." in relative_path.parts:
            raise ArtifactStorageError(
                f"Artifact storage reference contains path traversal: {storage_ref}"
            )

        path = (self._root / Path(*relative_path.parts)).resolve()

        try:
            path.relative_to(self._root)
        except ValueError as exc:
            raise ArtifactStorageError(
                f"Artifact storage reference escapes storage root: {storage_ref}"
            ) from exc

        return path


# Verify that the implementation satisfies the application port.
_: type[ArtifactStorage] = LocalArtifactStorage
