"""Non-fatal environment diagnostics."""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from core.cache import resolve_cache_path
from core.process_env import command_found
from core.security import sanitize_message


def run_doctor(project_root: Path, config: dict[str, Any]) -> list[tuple[str, bool | None, str]]:
    cache_path = resolve_cache_path(project_root, config["app"]["cache_path"])
    env_path = project_root / ".env"
    checks: list[tuple[str, bool | None, str]] = []
    checks.append(("Python", sys.version_info >= (3, 10), sys.version.split()[0]))
    for label, module in (("PySide6", "PySide6"), ("PyYAML", "yaml"), ("python-dotenv", "dotenv")):
        checks.append((label, *_module_check(module)))
    checks.append((".env file", True if env_path.exists() else None,
                   "found" if env_path.exists() else "optional; credentials may come from environment"))
    checks.append(("Cache writable", *_check_writable(cache_path)))
    for key, label in (("kimi", "Kimi"), ("deepseek", "DeepSeek"), ("codex", "Codex")):
        section = config.get(key, {})
        if not section.get("enabled", True):
            checks.append((f"{label} provider", None, "disabled; checks skipped"))
            continue
        if key == "kimi":
            has_key = bool(os.getenv("KIMI_API_KEY") or os.getenv("KIMI_CODING_API_KEY"))
            checks.append(("Kimi credentials", has_key,
                           "set" if has_key else "set KIMI_API_KEY or KIMI_CODING_API_KEY in .env or environment"))
            from providers.kimi_provider import _command_executable
            executable = _command_executable(str(section.get("command") or "kimi-usage --json"))
            found = bool(executable and command_found(executable))
            checks.append(("Kimi command", found, "found" if found else "install kimi-code-usage or correct kimi.command"))
        elif key == "deepseek":
            has_key = bool(os.getenv("DEEPSEEK_API_KEY"))
            checks.append(("DEEPSEEK_API_KEY", has_key,
                           "set" if has_key else "set DEEPSEEK_API_KEY in .env or environment"))
            daily_path = resolve_cache_path(project_root, section.get("daily_snapshot_path", "data/deepseek_daily.json"))
            checks.append(("DeepSeek daily snapshot", True if daily_path.exists() else None,
                           "exists" if daily_path.exists() else "created after first successful refresh"))
        else:
            command = str(section.get("custom_command") or "").strip()
            if section.get("mode") == "custom_command" or command:
                from providers.codex_provider import _command_executable
                executable = _command_executable(command)
                found = bool(executable and command_found(executable))
                checks.append(("Codex custom command", found, "found" if found else "configure an existing custom_command"))
            else:
                auth_path = Path.home() / ".codex" / "auth.json"
                checks.append(("Codex login file", auth_path.exists(),
                               "exists (content hidden; refresh verifies session)" if auth_path.exists() else "run codex login"))
                checks.append(("Codex usage source", None, "OAuth; run refresh to verify network and session"))
    config_path = project_root / "config.yaml"
    checks.append(("config.yaml", config_path.exists(), "exists" if config_path.exists() else "not found"))
    return checks


def format_doctor(checks: list[tuple[str, bool | None, str]]) -> str:
    lines = ["CODING PLAN WIDGET DOCTOR", ""]
    for label, ok, detail in checks:
        state = "INFO" if ok is None else "OK" if ok else "WARN"
        lines.append(f"[{state}] {label}: {sanitize_message(detail)}")
    return "\n".join(lines)


def _check_writable(cache_path: Path) -> tuple[bool, str]:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=cache_path.parent, prefix=".doctor-", delete=True):
            pass
        return True, str(cache_path)
    except OSError as exc:
        return False, sanitize_message(exc)


def _module_check(name: str) -> tuple[bool, str]:
    found = importlib.util.find_spec(name) is not None
    return found, "installed" if found else "not installed"


def _set_text(name: str) -> str:
    return "set" if os.getenv(name) else "not set"


def _found_text(command: str) -> str:
    return "found" if command_found(command) else "not found"
