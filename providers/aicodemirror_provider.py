"""Read-only wallet collection through an isolated Chromium helper."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import re
import subprocess
import sys

from providers.base import BaseProvider
from core.aicodemirror_session import session_path


def result(status="unsupported", message="", **values):
    return {"name": "AICodeMirror", "status": status, "balance": None, "message": message, **values}


def parse_wallet(payload):
    if not isinstance(payload, dict) or payload.get("success") is not True or not isinstance(payload.get("data"), dict):
        return result("error", "钱包响应格式无效，请检查网站登录状态。")
    amount = payload["data"].get("bonusBalance")
    if isinstance(amount, bool) or not isinstance(amount, (int, str)) or not re.fullmatch(r"-?\d{1,16}", str(amount)):
        return result("error", "钱包响应缺少有效的按量余额（整数厘）。")
    total = Decimal(str(amount)) / 1000
    display = f"{total:.3f}"
    if display.endswith("0"):
        display = display[:-1]  # Keep at least two decimals; a third is needed for 厘.
    return result("ok", balance={"currency": "CNY", "total": float(total), "display": f"¥{display}"},
                  lastSuccessAt=datetime.now().astimezone().isoformat(timespec="seconds"))


def browser_command(root: Path, mode: str, timeout: float = 30):
    args = ["aicodemirror-browser", "--browser-mode", mode, "--browser-root", str(root), "--browser-timeout", str(timeout)]
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    executable = Path(sys.executable)
    return [str(executable), str(Path(__file__).resolve().parents[1] / "main.py"), *args]


def parse_helper_output(output: str):
    # Chromium diagnostics are not forwarded into logs or the shared cache.
    for line in reversed(output.splitlines()):
        if line.startswith("AICM_RESULT:"):
            try:
                data = json.loads(line[len("AICM_RESULT:"):])
            except ValueError:
                continue
            if isinstance(data, dict) and data.get("status") in {"ok", "offline", "error", "unsupported"}:
                return data
    return result("error", "余额浏览器未正常完成，请重新登录或检查浏览器组件。")


class AICodeMirrorProvider(BaseProvider):
    key = "aicodemirror"
    display_name = "AICodeMirror"

    def __init__(self, config=None, project_root=None):
        super().__init__(config)
        self.root = project_root or Path.cwd()

    def collect(self):
        if not self.config.get("enabled", False):
            return result(message="AICodeMirror 未启用。")
        if not session_path(self.root).exists():
            return result(message="请在设置中登录 AICodeMirror。", needsLogin=True)
        configured = self.config.get("browser_timeout_seconds", 45)
        timeout = float(configured) if isinstance(configured, (int, float)) and 1 <= configured <= 120 else 45
        try:
            process = subprocess.run(browser_command(self.root, "query", timeout),
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout + 12,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return parse_helper_output(process.stdout)
        except subprocess.TimeoutExpired:
            return result("offline", "余额查询超时，保留上次数据。")
        except (OSError, ValueError):
            return result("error", "无法启动余额查询浏览器，请检查 PySide6 WebEngine 安装。")
