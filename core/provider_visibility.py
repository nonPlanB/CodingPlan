"""Independent taskbar selection, with compatibility for older settings."""

PROVIDER_KEYS = ("codex", "kimi", "deepseek", "aicodemirror", "relayrouter")


def taskbar_provider_keys(config):
    ui = config.get("ui", {})
    selected = ui.get("taskbar_providers")
    if selected is None:
        selected = ui.get("visible_providers", ["codex", "kimi", "deepseek"])
    return [key for key in PROVIDER_KEYS if key in selected
            and config.get(key, {}).get("enabled", True)]
