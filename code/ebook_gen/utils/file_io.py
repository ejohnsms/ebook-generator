"""File I/O utilities with atomic write operations.

Also provides the StorageAdapter abstraction for Phase 0 microservices seam.
Set STORAGE_BACKEND=minio to route artifact writes through MinIO instead of
the local filesystem (requires MINIO_* env vars).  Default: filesystem.
"""

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Union


def atomic_write(target_path: Path, content: Union[str, bytes]) -> None:
    """Write content to a file atomically.

    Uses write-to-temp-then-rename pattern to prevent corruption.

    Steps:
    1. Write to target_path.tmp in the same directory
    2. Flush and fsync
    3. Rename target_path.tmp -> target_path (atomic on POSIX)

    This ensures that target_path is never in a partially-written state.
    If the process crashes during write, only the .tmp file is corrupted
    and the previous version of target_path remains intact.

    Args:
        target_path: Path to the target file
        content: String or bytes to write

    Raises:
        OSError: If write or rename fails
    """
    # Ensure parent directory exists
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Create temp file path in same directory
    tmp_path = target_path.with_suffix(target_path.suffix + ".tmp")

    # Determine write mode
    mode = "wb" if isinstance(content, bytes) else "w"
    encoding = None if isinstance(content, bytes) else "utf-8"

    # Write to temp file
    with open(tmp_path, mode, encoding=encoding) as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())

    # Atomic rename
    tmp_path.rename(target_path)


def ensure_directory(directory: Path) -> None:
    """Ensure a directory exists, creating it if necessary.

    Args:
        directory: Path to the directory
    """
    directory.mkdir(parents=True, exist_ok=True)


def safe_read_text(file_path: Path) -> str:
    """Read text file with error handling.

    Args:
        file_path: Path to the file

    Returns:
        File contents as string

    Raises:
        FileNotFoundError: If file doesn't exist
        PermissionError: If file can't be read
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def safe_write_text(file_path: Path, content: str) -> None:
    """Write text file with atomic write.

    Args:
        file_path: Path to the file
        content: Text content to write
    """
    atomic_write(file_path, content)


# ---------------------------------------------------------------------------
# StorageAdapter — Phase 0 microservices seam
# ---------------------------------------------------------------------------


class StorageAdapter(ABC):
    """Abstract storage adapter.

    Both the filesystem (monolith) and MinIO (microservices) backends
    implement this interface.  Services that use StorageAdapter pass only
    string keys (MinIO-style paths like ``stories/{story_id}/raw.md``)
    and never touch ``Path`` objects directly.

    Key convention mirrors the MinIO bucket layout::

        stories/{story_id}/raw.md
        stories/{story_id}/story.md
        stories/{story_id}/story_{lang}.md
        images/{story_id}/scene_01.png
        compiled/{story_id}/{story_id}_{lang}_{mode}.epub
        audio/{story_id}/{story_id}_{lang}.wav
    """

    @abstractmethod
    def read(self, key: str) -> str:
        """Read a text artifact by key."""

    @abstractmethod
    def read_bytes(self, key: str) -> bytes:
        """Read a binary artifact by key."""

    @abstractmethod
    def write(self, key: str, content: str) -> None:
        """Write a text artifact atomically."""

    @abstractmethod
    def write_bytes(self, key: str, content: bytes) -> None:
        """Write a binary artifact atomically."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return True if the artifact exists."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete an artifact (no-op if missing)."""

    @abstractmethod
    def list_keys(self, prefix: str) -> List[str]:
        """List all keys with the given prefix."""


class FilesystemAdapter(StorageAdapter):
    """StorageAdapter backed by the local filesystem.

    ``root_dir`` is the project root; keys are resolved relative to it,
    so ``stories/foo/raw.md`` → ``{root_dir}/stories/foo/raw.md``.

    All writes use :func:`atomic_write` for crash safety.
    """

    def __init__(self, root_dir: Path):
        self._root = root_dir

    def _resolve(self, key: str) -> Path:
        return self._root / key

    def read(self, key: str) -> str:
        return safe_read_text(self._resolve(key))

    def read_bytes(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return path.read_bytes()

    def write(self, key: str, content: str) -> None:
        atomic_write(self._resolve(key), content)

    def write_bytes(self, key: str, content: bytes) -> None:
        atomic_write(self._resolve(key), content)

    def exists(self, key: str) -> bool:
        return self._resolve(key).exists()

    def delete(self, key: str) -> None:
        path = self._resolve(key)
        if path.exists():
            path.unlink()

    def list_keys(self, prefix: str) -> List[str]:
        base = self._resolve(prefix)
        if not base.exists():
            return []
        if base.is_file():
            return [prefix]
        return [
            str(p.relative_to(self._root))
            for p in sorted(base.rglob("*"))
            if p.is_file()
        ]


class MinioAdapter(StorageAdapter):
    """StorageAdapter backed by MinIO (S3-compatible object storage).

    Not yet implemented — will be wired up in Phase 1 when the MinIO
    infrastructure is deployed.  Raises ``NotImplementedError`` on every
    call so that accidental use during development fails loudly.

    Required env vars when activated::

        MINIO_ENDPOINT   (default: localhost:9000)
        MINIO_ACCESS_KEY (default: minioadmin)
        MINIO_SECRET_KEY (default: minioadmin)
        MINIO_BUCKET     (default: ebook-gen)
        MINIO_SECURE     (default: false)
    """

    def __init__(self, config=None):
        # config is MinioConfig; accepted here so the constructor signature
        # is consistent, but the client is not created until Phase 1.
        self._config = config

    def _not_implemented(self) -> None:
        raise NotImplementedError(
            "MinioAdapter is a Phase 1 stub. "
            "Deploy MinIO infrastructure and install the minio SDK before enabling."
        )

    def read(self, key: str) -> str:
        self._not_implemented()

    def read_bytes(self, key: str) -> bytes:
        self._not_implemented()

    def write(self, key: str, content: str) -> None:
        self._not_implemented()

    def write_bytes(self, key: str, content: bytes) -> None:
        self._not_implemented()

    def exists(self, key: str) -> bool:
        self._not_implemented()

    def delete(self, key: str) -> None:
        self._not_implemented()

    def list_keys(self, prefix: str) -> List[str]:
        self._not_implemented()


def get_storage_adapter(root_dir: Path) -> StorageAdapter:
    """Factory: return the StorageAdapter selected by STORAGE_BACKEND env var.

    Args:
        root_dir: Project root directory (used by FilesystemAdapter).

    Returns:
        FilesystemAdapter when STORAGE_BACKEND=filesystem (default).
        MinioAdapter     when STORAGE_BACKEND=minio.
    """
    backend = os.getenv("STORAGE_BACKEND", "filesystem").lower()
    if backend == "minio":
        from ..config import MinioConfig
        return MinioAdapter(MinioConfig.from_env())
    return FilesystemAdapter(root_dir)
