import hashlib
import os
from functools import wraps
from pathlib import Path
from uuid import UUID

from leornian.modules.knowledge.file_contracts import MAX_FILE_BYTES
from leornian.shared_kernel.errors import BusinessError


def storage_errors(operation):
    @wraps(operation)
    def safe(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except OSError:
            raise BusinessError(
                "material_storage_unavailable", "Original storage is unavailable."
            ) from None

    return safe


class OriginalFileStore:
    """Only knowledge-owned UUID references address originals; filenames never do."""

    def __init__(self, directory):
        self.root = Path(directory).expanduser().resolve()

    def _path(self, actor_id, upload_id):
        parent = self.root / str(UUID(str(actor_id)))
        path = parent / (str(UUID(str(upload_id))) + ".blob")
        if parent.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise BusinessError("material_storage_unavailable", "Original storage is unavailable.")
        return path

    @staticmethod
    def check(content, expected_digest, byte_size):
        if (
            len(content) != byte_size
            or len(content) > MAX_FILE_BYTES
            or hashlib.sha256(content).hexdigest() != expected_digest
        ):
            raise BusinessError(
                "material_content_mismatch", "File does not match its upload reference."
            )

    @storage_errors
    def put(self, actor_id, upload_id, content, expected_digest, byte_size):
        self.check(content, expected_digest, byte_size)
        path = self._path(actor_id, upload_id)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.exists():
            self.check(self.read(actor_id, upload_id), expected_digest, byte_size)
            return
        temporary = path.with_suffix(".pending")
        try:
            temporary.unlink(missing_ok=True)
            with temporary.open("xb") as out:
                os.chmod(temporary, 0o600)
                out.write(content)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @storage_errors
    def read(self, actor_id, upload_id):
        path = self._path(actor_id, upload_id)
        try:
            with path.open("rb") as stream:
                content = stream.read(MAX_FILE_BYTES + 1)
        except FileNotFoundError:
            raise BusinessError(
                "material_original_missing", "Original file is unavailable."
            ) from None
        if len(content) > MAX_FILE_BYTES:
            raise BusinessError("material_content_mismatch", "Stored original exceeds its limit.")
        return content

    @storage_errors
    def delete(self, actor_id, upload_id):
        path = self._path(actor_id, upload_id)
        path.unlink(missing_ok=True)
        path.with_suffix(".pending").unlink(missing_ok=True)
