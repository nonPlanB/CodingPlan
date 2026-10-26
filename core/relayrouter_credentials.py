"""RelayRouter credentials are stored separately from application settings."""
import json
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4

from core.aicodemirror_session import protect


def credentials_path(root: Path) -> Path:
    return root / "data" / "relayrouter.credentials.dpapi"


def validate_credentials(user_id, access_token):
    user_id = str(user_id).strip()
    if not isinstance(access_token, str):
        raise ValueError("请输入有效的身份验证令牌。")
    access_token = access_token.strip()
    if not re.fullmatch(r"[1-9][0-9]{0,15}", user_id):
        raise ValueError("请输入有效的 RelayRouter 数字用户 ID。")
    if not access_token or len(access_token) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in access_token):
        raise ValueError("请输入有效的身份验证令牌，不能包含空格或换行。")
    return {"user_id": user_id, "access_token": access_token}


def load_credentials(root: Path):
    path = credentials_path(root)
    if not path.exists():
        return None
    try:
        if path.stat().st_size > 16384:
            raise ValueError()
        data = json.loads(protect(path.read_bytes(), decrypt=True))
        if data.get("version") != 1 or not isinstance(data.get("revision"), str):
            raise ValueError()
        values = validate_credentials(data["user_id"], data["access_token"])
        return {**values, "revision": data["revision"]}
    except (ValueError, KeyError, TypeError, AttributeError, OSError):
        raise ValueError("无法读取 RelayRouter 加密凭据，请重新保存或清除凭据。") from None


def clear_cached_balance(root: Path):
    from core.cache import read_usage, resolve_cache_path, write_usage
    from core.collector import load_config
    cache = resolve_cache_path(root, load_config(root)["app"]["cache_path"])
    usage = read_usage(cache, create_if_missing=False)
    if "relayrouter" in usage.get("providers", {}):
        usage["providers"].pop("relayrouter")
        write_usage(cache, usage)


def save_credentials(root: Path, user_id, access_token):
    values = {"version": 1, **validate_credentials(user_id, access_token), "revision": uuid4().hex}
    ciphertext = protect(json.dumps(values).encode(), description="CodingPlan RelayRouter credentials")
    path = credentials_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".relayrouter-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(ciphertext)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    clear_cached_balance(root)


def clear_credentials(root: Path):
    credentials_path(root).unlink(missing_ok=True)
    clear_cached_balance(root)
