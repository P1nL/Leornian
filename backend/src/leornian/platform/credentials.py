import ctypes
import json
import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from leornian.shared_kernel.errors import BusinessError


def _dpapi(data: bytes, entropy: bytes, *, decrypt: bool) -> bytes:
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    def blob(value):
        buffer = ctypes.create_string_buffer(value)
        return Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer

    source, source_buffer = blob(data)
    extra, extra_buffer = blob(entropy)
    output = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        operation = crypt.CryptUnprotectData
        operation.argtypes = [
            ctypes.POINTER(Blob),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(Blob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(Blob),
        ]
        args = [
            ctypes.byref(source),
            None,
            ctypes.byref(extra),
            None,
            None,
            1,
            ctypes.byref(output),
        ]
    else:
        operation = crypt.CryptProtectData
        operation.argtypes = [
            ctypes.POINTER(Blob),
            wintypes.LPCWSTR,
            ctypes.POINTER(Blob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(Blob),
        ]
        args = [
            ctypes.byref(source),
            "Leornian model credential",
            ctypes.byref(extra),
            None,
            None,
            1,
            ctypes.byref(output),
        ]
    operation.restype = wintypes.BOOL
    if not operation(*args):
        raise BusinessError("model_unavailable", "Local credential protection is unavailable.")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


class CredentialVault:
    """DPAPI for a native Windows backend; an OS-protected secret file for local Linux."""

    def __init__(self, master_file: str = ""):
        self.master_file = master_file

    def _fernet(self):
        path = Path(self.master_file)
        if not self.master_file or not path.is_absolute() or path.is_symlink():
            raise BusinessError(
                "model_unavailable", "Configure local protected credential storage."
            )
        try:
            metadata = path.stat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or metadata.st_mode & 0o077
            ):
                raise ValueError("unsafe_master_file")
            return Fernet(path.read_bytes().strip())
        except (OSError, ValueError):
            raise BusinessError(
                "model_unavailable", "Local credential storage is unavailable or not protected."
            ) from None

    def available(self):
        try:
            if os.name == "nt":
                return True
            self._fernet()
            return True
        except BusinessError:
            return False

    @staticmethod
    def _scope(owner, connection_id, version):
        return f"leornian:model:{owner}:{connection_id}:{version}".encode()

    def seal(self, owner, connection_id, version, secret):
        scope = self._scope(owner, connection_id, version)
        payload = json.dumps({"scope": scope.decode(), "secret": secret}).encode()
        if os.name == "nt":
            return "dpapi.v1", _dpapi(payload, scope, decrypt=False)
        return "fernet.v1", self._fernet().encrypt(payload)

    def open(self, owner, connection_id, version, scheme, ciphertext):
        scope = self._scope(owner, connection_id, version)
        try:
            if scheme == "dpapi.v1" and os.name == "nt":
                raw = _dpapi(bytes(ciphertext), scope, decrypt=True)
            elif scheme == "fernet.v1" and os.name != "nt":
                raw = self._fernet().decrypt(bytes(ciphertext))
            else:
                raise ValueError("unsupported_local_store")
            payload = json.loads(raw)
            if payload["scope"] != scope.decode():
                raise ValueError("credential_scope_mismatch")
            return payload["secret"]
        except (InvalidToken, ValueError, KeyError, TypeError):
            raise BusinessError(
                "model_unavailable", "Local credential cannot be resolved."
            ) from None


def initialize_local_master(master_file):
    if os.name == "nt":
        return  # Native Windows uses the current OS user's DPAPI, not a plaintext root key.
    path = Path(master_file)
    if not master_file or not path.is_absolute() or path.is_symlink():
        raise ValueError("An absolute local master-file location is required")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    metadata = path.parent.stat()
    if metadata.st_uid != os.geteuid() or path.parent.is_symlink():
        raise ValueError("Credential directory is not owned by this local backend")
    path.parent.chmod(0o700)
    try:
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
    except FileExistsError:
        CredentialVault(str(path))._fernet()
        return
    with os.fdopen(descriptor, "wb") as target:
        target.write(Fernet.generate_key())
        target.flush()
        os.fsync(target.fileno())


def main():
    import argparse

    from leornian.platform.config import Settings

    parser = argparse.ArgumentParser(description="Initialize protected local model credentials")
    parser.add_argument("--initialize", action="store_true", required=True)
    parser.parse_args()
    initialize_local_master(Settings().credential_master_file)
    print("Local credential storage is initialized; existing keys are not replaced.")


if __name__ == "__main__":
    main()
