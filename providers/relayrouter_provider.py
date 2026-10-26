"""Read-only account balance API. Never sends model inference requests."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import urllib.error
import urllib.request

from core.cache import read_usage, resolve_cache_path
from core.relayrouter_credentials import load_credentials, validate_credentials
from providers.base import BaseProvider

ORIGIN = "https://www.relayrouter.app"


def result(status="unsupported", message="", **values):
    return {"name": "RelayRouter", "status": status, "balance": None, "message": message, **values}


class QueryError(Exception):
    def __init__(self, reading):
        self.reading = reading


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _get(path, headers, timeout, use_system_proxy):
    handlers = [NoRedirect()]
    if not use_system_proxy:
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(ORIGIN + path, headers={"Accept": "application/json",
        "User-Agent": "CodingPlanWidget/1.3", **headers}, method="GET")
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError()
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError()
        return payload
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            reading = result("error", "认证失败，请检查用户 ID 和身份验证令牌。", needsLogin=True)
        elif exc.code == 429:
            reading = result("error", "查询过于频繁，请稍后重试。")
        elif 300 <= exc.code < 400:
            reading = result("error", "查询接口发生重定向，为保护令牌已停止请求。")
        else:
            reading = result("error", f"余额服务暂时不可用（HTTP {exc.code}）。")
        raise QueryError(reading) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise QueryError(result("offline", "无法连接 RelayRouter，请检查网络或代理设置。")) from None
    except (ValueError, UnicodeError):
        raise QueryError(result("error", "RelayRouter 返回的账户数据格式无效。")) from None


def parse_balance(account, settings):
    try:
        if account.get("success") is not True or settings.get("success") is not True:
            raise ValueError()
        quota = account["data"]["quota"]
        unit = settings["data"]["quota_per_unit"]
        if isinstance(quota, bool) or isinstance(unit, bool):
            raise ValueError()
        if not isinstance(quota, int) or not isinstance(unit, (int, float)):
            raise ValueError()
        amount, divisor = Decimal(str(quota)), Decimal(str(unit))
        if not divisor.is_finite() or divisor <= 0:
            raise ValueError()
        total = amount / divisor
        if not total.is_finite() or abs(total) > Decimal("1e15"):
            raise ValueError()
        return result("ok", balance={"currency": "USD", "total": float(total), "display": f"${total:.2f}"},
                      lastSuccessAt=datetime.now().astimezone().isoformat(timespec="seconds"))
    except (KeyError, TypeError, AttributeError, ValueError, InvalidOperation, ArithmeticError):
        return result("error", "账户余额或额度换算数据无效，未将缺失余额视为零。")


def query_balance(credentials, timeout=15, use_system_proxy=False):
    try:
        values = validate_credentials(credentials["user_id"], credentials["access_token"])
    except (ValueError, TypeError, KeyError):
        return result(message="请配置 RelayRouter 用户 ID 和身份验证令牌。", needsLogin=True)
    try:
        account = _get("/api/user/self", {"Authorization": "Bearer " + values["access_token"],
                         "New-Api-User": values["user_id"]}, timeout, use_system_proxy)
        if account.get("success") is not True:
            return result("error", "账户查询未成功，请检查凭据或稍后重试。")
        # The public conversion endpoint receives no user ID or token.
        settings = _get("/api/status", {}, timeout, use_system_proxy)
        return parse_balance(account, settings)
    except QueryError as exc:
        return exc.reading


class RelayRouterProvider(BaseProvider):
    key, display_name = "relayrouter", "RelayRouter"

    def __init__(self, config=None, project_root=None, *, force=False, cache_path=None):
        super().__init__(config)
        self.root = project_root or Path.cwd()
        self.force = force
        self.cache_path = cache_path or self.root / "data" / "usage.json"

    def collect(self):
        if not self.config.get("enabled", False):
            return result(message="RelayRouter 未启用。")
        try:
            credentials = load_credentials(self.root)
        except ValueError:
            return result("error", "无法读取加密凭据，请在设置中重新保存凭据。", needsLogin=True)
        if not credentials:
            return result(message="请在设置中配置 RelayRouter 凭据。", needsLogin=True)
        revision = credentials["revision"]
        if not self.force:
            cached = read_usage(self.cache_path, create_if_missing=False).get("providers", {}).get(self.key, {})
            try:
                age = (datetime.now().astimezone() - datetime.fromisoformat(cached["lastSuccessAt"])).total_seconds()
                interval = max(30, int(self.config.get("refresh_interval_seconds", 300)))
                if cached.get("credentialRevision") == revision and cached.get("status") == "ok" and 0 <= age < interval:
                    return cached
            except (ValueError, KeyError, TypeError):
                pass
        reading = query_balance(credentials, self.timeout_seconds, self.config.get("use_system_proxy", False))
        reading["credentialRevision"] = revision
        try:
            current = load_credentials(self.root)
        except ValueError:
            current = None
        if not current or current["revision"] != revision:
            return result(message="凭据已更改，请刷新以查询当前账户。")
        return reading
