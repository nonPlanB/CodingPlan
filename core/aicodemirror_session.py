"""Windows user-bound encryption for the isolated AICodeMirror cookie jar.

No password, API key, localStorage, or third-party login cookies are persisted.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile

SITE = "https://www.aicodemirror.ai"


def session_path(root: Path) -> Path:
    return root / "data" / "aicodemirror.session.dpapi"


def protect(data: bytes, *, decrypt: bool = False, description: str = "CodingPlan AICodeMirror session") -> bytes:
    if os.name != "nt":
        raise OSError("加密凭据需要 Windows DPAPI。")

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, target = Blob(len(data), buf), Blob()
    if decrypt:
        fn = crypt.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    else:
        fn = crypt.CryptProtectData
        fn.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = fn(ctypes.byref(source), description, None,
                None, None, 1, ctypes.byref(target))
    fn.restype = wintypes.BOOL
    if not ok:
        raise OSError("无法读取或加密凭据，请在当前 Windows 用户下重新配置。")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def load_session(root: Path) -> dict:
    path = session_path(root)
    if not path.exists():
        return {"version": 1, "cookies": []}
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("登录会话文件无效，请清除后重新登录。")
    result = json.loads(protect(path.read_bytes(), decrypt=True))
    if not isinstance(result, dict) or result.get("version") != 1 or not isinstance(result.get("cookies"), list):
        raise ValueError("登录会话文件无效，请清除后重新登录。")
    return result


def save_session(root: Path, session: dict) -> None:
    # Encrypt before creating a temporary file: plaintext never reaches disk.
    encrypted = protect(json.dumps(session, separators=(",", ":")).encode())
    path = session_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".aicodemirror-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encrypted)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def session_lock(root: Path):
    """Serialize login, background refresh and logout across processes."""
    if os.name != "nt":
        raise OSError("登录会话需要 Windows。")
    import msvcrt
    path = session_path(root).with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise OSError("AICodeMirror 正在登录或刷新，请稍后重试。") from None
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def clear_session(root: Path) -> None:
    from core.cache import read_usage, resolve_cache_path, write_usage
    from core.collector import load_config
    with session_lock(root):
        session_path(root).unlink(missing_ok=True)
        cache = resolve_cache_path(root, load_config(root)["app"]["cache_path"])
        usage = read_usage(cache, create_if_missing=False)
        usage.get("providers", {}).pop("aicodemirror", None)
        write_usage(cache, usage)
