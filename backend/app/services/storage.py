"""Local byte storage for uploaded PDFs.

Keys are content hashes, not file names. A later object-storage implementation
can keep the same two operations.
"""

import re
from pathlib import Path
from typing import Protocol

_KEY = re.compile(r"^[a-f0-9]{2}/[a-f0-9]{64}\.pdf$")


class DocumentStore(Protocol):
    def put_if_absent(self, key: str, data: bytes) -> None: ...

    def read(self, key: str) -> bytes: ...


class StorageError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class LocalDocumentStore:
    """Write PDF bytes under a root directory outside the application package."""

    def __init__(self, root: Path) -> None:
        resolved = root.expanduser().resolve()
        package = Path(__file__).resolve().parents[1]
        if resolved == package or package in resolved.parents:
            raise StorageError("Document storage cannot live inside the application package.")
        self._root = resolved

    def put_if_absent(self, key: str, data: bytes) -> None:
        path = self._path(key)
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.part")
        temporary.write_bytes(data)
        temporary.replace(path)

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def _path(self, key: str) -> Path:
        if _KEY.fullmatch(key) is None:
            raise StorageError("The storage key is not a content hash.")
        path = (self._root / key).resolve()
        if path != self._root and self._root not in path.parents:
            raise StorageError("The storage key escapes the storage root.")
        return path


def storage_key(digest: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise StorageError("The content hash is not a SHA-256 digest.")
    return f"{digest[:2]}/{digest}.pdf"
