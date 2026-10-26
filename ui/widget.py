"""Frameless, draggable desktop usage widget."""

from __future__ import annotations

import os
from datetime import datetime
from copy import deepcopy
import subprocess
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, QRect, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QMouseEvent, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QDialog,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.cache import read_usage, resolve_cache_path
from core.collector import collect_usage, load_config
from core.freshness import compute_cache_freshness, format_updated_with_freshness
from core.time_display import format_reset_time
from core.paths import application_icon_path, data_path, project_root as project_root_func
from core.security import sanitize_message
from core.provider_visibility import taskbar_provider_keys
from core.ui_state import read_ui_state, write_ui_state
from ui.settings import SettingsDialog
from ui.taskbar import TaskbarQuotaStrip, logo_path

COLOR_NORMAL = "#65d6a6"
COLOR_WARNING = "#f5c451"
COLOR_DANGER = "#ff6b7a"
COLOR_MUTED = "#87909f"


def _localized_updated(value) -> str:
    text = format_updated_with_freshness(value)
    for old, new in (("Updated", "更新于"), ("Fresh", "已同步"), ("Stale", "数据陈旧"),
                     ("Expired", "已过期"), ("Unknown", "尚未同步")):
        text = text.replace(old, new)
    return text


class RefreshThread(QThread):
    completed = Signal()
    failed = Signal(str)

    def __init__(self, project_root: Path, config: dict[str, Any], force=False) -> None:
        super().__init__()
        self.project_root = project_root
        self.config = config
        self.force = force

    def run(self) -> None:
        try:
            collect_usage(self.project_root, self.config, force=self.force)
        except Exception as exc:
            self.failed.emit(sanitize_message(exc))
        else:
            self.completed.emit()


class ProviderCard(QFrame):
    def __init__(self, title: str, show_reset: bool = True) -> None:
        super().__init__()
        self.light = False
        self.show_reset = show_reset
        self.bars = {}
        self.row_names = {}
        self.reset_labels = {}
        self.setObjectName("providerCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        header = QHBoxLayout()
        self.provider_key = title.lower()
        self.logo = QLabel()
        self.logo.setFixedSize(24, 24)
        header.addWidget(self.logo)
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        self.status = QLabel("未配置")
        self.status.setObjectName("providerStatus")
        header.addWidget(self.title)
        header.addStretch()
        header.addWidget(self.status)
        layout.addLayout(header)
        self._setup_rows(layout)
        self.message = QLabel("")
        self.message.setObjectName("message")
        self.message.setWordWrap(True)
        self.message.hide()
        layout.addWidget(self.message)

    def _setup_rows(self, layout: QVBoxLayout) -> None:
        self.five = self._row("5H", layout)
        self.week = self._row("WEEK", layout)

    def _row(self, label: str, layout: QVBoxLayout) -> QLabel:
        row = QHBoxLayout()
        name = QLabel({"5H": "5 小时剩余", "WEEK": "每周剩余", "BAL": "账户余额", "TODAY": "今日消费估算"}[label])
        name.setObjectName("quotaName")
        self.row_names[label] = name
        row.addWidget(name)
        row.addStretch()
        widget = QLabel("--")
        widget.setObjectName("quota")
        row.addWidget(widget)
        layout.addLayout(row)
        if label in ("5H", "WEEK"):
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(False)
            bar.setFixedHeight(5)
            layout.addWidget(bar)
            self.bars[label] = bar
            reset = QLabel()
            reset.setObjectName("resetTime")
            self.reset_labels[label] = reset
            layout.addWidget(reset)
        return widget

    def update_data(self, data: dict[str, Any]) -> None:
        self.logo.setPixmap(QIcon(str(logo_path(self.provider_key, self.light))).pixmap(64, 64).scaled(
            24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        status = data.get("status", "error")
        self.status.setText({"ok": "● 已同步", "offline": "离线", "error": "异常", "unsupported": "未启用 / 未配置"}.get(status, str(status)))
        self.status.setStyleSheet(
            f"color: {self._color(100, status)};"
        )
        self._update_rows(data, status)
        message = sanitize_message(data.get("message") or "", 160)
        self.message.setText(message)
        self.message.setVisible(bool(message) and status != "ok")

    def _update_rows(self, data: dict[str, Any], status: str) -> None:
        self._set_quota(self.five, "5H", data.get("fiveHour", {}), status)
        self._set_quota(self.week, "WEEK", data.get("weekly", {}), status)

    def _set_quota(self, label: QLabel, prefix: str, window: dict[str, Any], status: str) -> None:
        value = window.get("remainingPercent") if isinstance(window, dict) else None
        pct_text = "--" if value is None else f"{value:g}%"
        reset = format_reset_time(window.get("resetAt")) if isinstance(window, dict) else "--"
        stale = " · 已过期" if value is not None and status != "ok" else ""
        label.setText(pct_text)
        self.reset_labels[prefix].setText(f"重置于 {reset}{stale}")
        self.reset_labels[prefix].setVisible(self.show_reset or bool(stale))
        self.row_names[prefix].setToolTip("剩余额度")
        bar = self.bars[prefix]
        bar.setValue(max(0, min(100, round(value))) if isinstance(value, (int, float)) else 0)
        bar.setStyleSheet(f"QProgressBar::chunk {{ background: {self._color(value, status)}; border-radius: 2px; }}")
        label.setStyleSheet(f"color: {self._color(value, status)};")


    def _color(self, value, status):
        color = _quota_color(value, status)
        if self.light:
            return {COLOR_NORMAL: "#167858", COLOR_WARNING: "#926000", COLOR_DANGER: "#bd3144", COLOR_MUTED: "#586b84"}[color]
        return color


class DeepSeekCard(ProviderCard):
    def _setup_rows(self, layout: QVBoxLayout) -> None:
        self.bal = self._row("BAL", layout)
        self.today = self._row("TODAY", layout)

    def _update_rows(self, data: dict[str, Any], status: str) -> None:
        balance = data.get("balance") or {}
        today = data.get("today") or {}
        currency = str(balance.get("currency") or "UNKNOWN")
        total = balance.get("total")
        spend = today.get("estimatedSpend")
        total_text = "--" if total is None else f"{currency} {float(total):.2f}"
        spend_text = "--" if spend is None else f"~{currency} {float(spend):.2f}"
        stale = status != "ok"
        self.bal.setText(f"{total_text}{' · 已过期' if stale and total is not None else ''}")
        self.today.setText(
            f"{spend_text}{' · 已过期' if stale and spend is not None else ''}"
        )
        color = self._color(100 if status == "ok" else None, status)
        self.bal.setStyleSheet(f"color: {color};")
        self.today.setStyleSheet(f"color: {color};")


class AICodeMirrorCard(ProviderCard):
    balance_label = "按量付费余额"
    currency_symbol = "¥"

    def _setup_rows(self, layout):
        self.bal = self._row("BAL", layout)
        self.row_names["BAL"].setText(self.balance_label)
        self.timestamp = QLabel("尚未同步")
        self.timestamp.setObjectName("resetTime")
        layout.addWidget(self.timestamp)

    def _update_rows(self, data, status):
        balance = data.get("balance") or {}
        value = balance.get("total")
        text = balance.get("display") or (f"{self.currency_symbol}{value:.3f}" if value is not None else "--")
        self.bal.setText(text + (" · 已过期" if value is not None and status != "ok" else ""))
        self.bal.setStyleSheet(f"color: {self._color(100 if status == 'ok' else None, status)};")
        stamp = data.get("lastSuccessAt")
        try:
            success_time = datetime.fromisoformat(stamp).astimezone().strftime("%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            success_time = "--"
        self.timestamp.setText("上次成功：" + success_time)
        info = data.get("sessionInfo") or {}
        self.timestamp.setToolTip("已验证保存会话可恢复" if info.get("restoredSessionVerified") else "登录会话将在下一次刷新时验证恢复")


class RelayRouterCard(AICodeMirrorCard):
    balance_label = "账户余额（美元）"
    currency_symbol = "$"

    def _update_rows(self, data, status):
        super()._update_rows(data, status)
        value = (data.get("balance") or {}).get("total")
        self.bal.setToolTip(f"精确余额：USD {value:.6f}" if value is not None else "")
        self.timestamp.setToolTip("通过账户管理接口查询，不调用模型。")


class CodingPlanWidget(QWidget):
    def __init__(self, project_root: Path | None = None) -> None:
        super().__init__()
        self.project_root = project_root or project_root_func()
        self.config = load_config(self.project_root)
        self.cache_path = resolve_cache_path(self.project_root, self.config["app"]["cache_path"])
        self.state_path = self.project_root / "data" / "ui_state.json"
        self._refresh_pending = False
        self.drag_offset = None
        self.refresh_thread: RefreshThread | None = None
        self.exit_requested = False
        self.last_updated_at: Any = None
        self._taskbar_usage: dict[str, Any] = {}
        saved_state = read_ui_state(self.state_path)
        self.taskbar_strip = TaskbarQuotaStrip(saved_state.get("taskbar_offset", 0)) if os.name == "nt" else None
        if self.taskbar_strip is not None:
            self.taskbar_strip.restore_requested.connect(self.show_and_activate)
            self.taskbar_strip.offset_changed.connect(self._save_taskbar_offset)
            self.taskbar_strip.context_menu_requested.connect(self._show_context_menu)
        self.always_on_top = bool(
            saved_state.get("always_on_top", self.config["ui"].get("always_on_top", True))
        )
        self.collapsible = bool(self.config["ui"].get("collapsible", True))
        self.collapsed = self.collapsible and bool(saved_state.get("collapsed", False))
        self.click_title_to_toggle = bool(
            self.config["ui"].get("click_title_to_toggle_collapse", True)
        )
        self.collapsed_height = int(self.config["ui"].get("collapsed_height", 64))
        self.expanded_height = int(self.config["ui"].get("expanded_height", 300))
        self._drag_start: QPoint | None = None
        self._is_dragging = False
        self._drag_threshold = 4

        self.setWindowTitle("Coding Plan Widget")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(float(self.config["ui"].get("opacity", 0.92)))
        self.resize(int(self.config["ui"].get("width", 280)), int(self.config["ui"].get("height", 300)))
        self._apply_flags()
        self._build_ui()
        self._apply_style()
        self._setup_application_icon()
        self._restore_position(saved_state)
        self.load_cache()

        interval_ms = max(30, int(self.config["app"].get("refresh_interval_seconds", 180))) * 1000
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_data)
        self.timer.start(interval_ms)
        self.freshness_timer = QTimer(self)
        self.freshness_timer.timeout.connect(self._update_freshness)
        self.freshness_timer.start(60000)
        QTimer.singleShot(0, self.refresh_data)

    def _apply_flags(self) -> None:
        # Tool windows stay out of the Windows taskbar and its thumbnail list.
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(7)

        self.header_widget = QWidget(self)
        header = QHBoxLayout(self.header_widget)
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel(self.config["ui"].get("title", "Coding Energy"))
        self.title_label = title
        title.setObjectName("header")
        header.addWidget(title)
        self.face = QLabel("(?_?)")
        self.face.setObjectName("face")
        header.addWidget(self.face)
        self.face.hide()
        header.addStretch()

        self.settings_btn = QPushButton("设置")
        self.settings_btn.setObjectName("iconButton")
        self.settings_btn.setFixedSize(38, 28)
        self.settings_btn.setToolTip("设置")
        self.settings_btn.setAccessibleName("设置")
        self.settings_btn.clicked.connect(self.open_settings)
        header.addWidget(self.settings_btn)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setObjectName("iconButton")
        self.refresh_btn.setFlat(True)
        self.refresh_btn.setFixedSize(38, 28)
        self.refresh_btn.setToolTip("立即刷新额度")
        self.refresh_btn.clicked.connect(lambda: self.refresh_data(force=True))
        header.addWidget(self.refresh_btn)

        self.hide_btn = QPushButton("—")
        self.hide_btn.setObjectName("iconButton")
        self.hide_btn.setFixedSize(24, 26)
        self.hide_btn.setToolTip("隐藏主窗口（任务栏环形组件继续显示）")
        self.hide_btn.setAccessibleName("隐藏主窗口")
        self.hide_btn.clicked.connect(self.hide)
        header.addWidget(self.hide_btn)

        self.collapse_btn = QPushButton("˄")
        self.collapse_btn.setObjectName("iconButton")
        self.collapse_btn.setFlat(True)
        self.collapse_btn.setFixedSize(26, 26)
        self.collapse_btn.setToolTip("折叠 / 展开")
        self.collapse_btn.clicked.connect(self._toggle_collapse)
        self.collapse_btn.setVisible(self.collapsible)
        header.addWidget(self.collapse_btn)

        root.addWidget(self.header_widget)

        self.cards_widget = QWidget(self)
        cards_layout = QVBoxLayout(self.cards_widget)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(7)
        self.codex_card = ProviderCard("Codex")
        self.kimi_card = ProviderCard("Kimi")
        self.deepseek_card = DeepSeekCard("DeepSeek")
        self.aicodemirror_card = AICodeMirrorCard("AICodeMirror")
        self.relayrouter_card = RelayRouterCard("RelayRouter")
        cards_layout.addWidget(self.codex_card)
        cards_layout.addWidget(self.kimi_card)
        cards_layout.addWidget(self.deepseek_card)
        cards_layout.addWidget(self.aicodemirror_card)
        cards_layout.addWidget(self.relayrouter_card)
        self.empty_label = QLabel("暂无显示的数据源，请在设置中选择。")
        self.empty_label.setObjectName("message")
        self.empty_label.setWordWrap(True)
        cards_layout.addWidget(self.empty_label)
        root.addWidget(self.cards_widget)

        self.summary = QLabel("")
        self.summary.setObjectName("summary")
        self.summary.setMinimumWidth(0)
        self.summary.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.summary.hide()
        root.addWidget(self.summary)

        self.updated = QLabel("更新于 --:--")
        self.updated.setObjectName("updated")
        root.addWidget(self.updated)

        self._apply_provider_visibility()
        self._apply_collapse_state(initial=True)

    def _apply_style(self) -> None:
        light = self.config["ui"].get("theme") == "light"
        text, muted, card, border = ("#202126", "#737681", "#ffffff", "#e2e3e8") if light else ("#f2f2f5", "#92929d", "#1b1b20", "#303038")
        self.setStyleSheet(f"""
            QWidget {{ color: {text}; font-family: "Segoe UI", "Microsoft YaHei UI"; font-size: 12px; }}
            #header {{ font-size: 15px; font-weight: 700; }}
            #face {{ color: #6c96f5; font-family: Consolas; font-weight: 700; }}
            #providerCard {{ background: {card}; border: 1px solid {border}; border-radius: 10px; }}
            #cardTitle {{ color: {text}; font-size: 14px; font-weight: 600; }}
            #providerStatus {{ color: {muted}; font-size: 10px; padding: 3px 6px; background: {border}; border-radius: 5px; }}
            #quota {{ font-family: "Segoe UI", "Microsoft YaHei UI"; font-size: 18px; font-weight: 600; }}
            #quotaName {{ color: {muted}; font-size: 12px; }}
            #resetTime, #message, #updated {{ color: {muted}; font-size: 11px; }}
            #iconButton {{ color: {muted}; font-size: 12px; border: none; border-radius: 6px; background: transparent; }}
            #iconButton:hover {{ background: {border}; color: {text}; }}
            #iconButton:disabled {{ color: #657085; }}
            #summary {{ color: {text}; font-family: Consolas; font-size: 11px; }}
            QProgressBar {{ background: {border}; border: none; border-radius: 2px; }}
            QMenu {{ background: {card}; color: {text}; border: 1px solid {border}; border-radius: 10px; padding: 6px; }}
            QMenu::item {{ padding: 8px 28px; border-radius: 5px; }}
            QMenu::item:selected {{ background: {border}; }}
            QMenu::item:disabled {{ color: {muted}; }}
            QMenu::separator {{ height: 1px; background: {border}; margin: 5px 8px; }}
        """)
        self.update()

    def _apply_provider_visibility(self) -> None:
        visible = self.config["ui"].get("visible_providers", ["codex", "kimi", "deepseek"])
        for key, card in (("codex", self.codex_card), ("kimi", self.kimi_card), ("deepseek", self.deepseek_card), ("aicodemirror", self.aicodemirror_card), ("relayrouter", self.relayrouter_card)):
            card.setVisible(key in visible)
            card.show_reset = self.config["ui"].get("show_reset_times", True)
            card.light = self.config["ui"].get("theme") == "light"
        self.empty_label.setVisible(not visible)

    def open_settings(self) -> None:
        config = deepcopy(self.config)
        config["ui"]["always_on_top"] = self.always_on_top
        dialog = SettingsDialog(self.project_root, config, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.load_cache()  # Local logout also takes effect when settings are cancelled.
            return
        self.config = dialog.config
        ui = self.config["ui"]
        self.title_label.setText(ui["title"])
        self.setWindowOpacity(ui["opacity"])
        position = self.pos()
        self.always_on_top = ui["always_on_top"]
        self._apply_flags()
        self.move(position)
        self.show()
        self.collapsible = ui["collapsible"]
        self.collapsed = self.collapsed and self.collapsible
        self.collapse_btn.setVisible(self.collapsible)
        self.expanded_height = ui["expanded_height"]
        self.timer.setInterval(self.config["app"]["refresh_interval_seconds"] * 1000)
        self._apply_provider_visibility()
        self._apply_style()
        self.load_cache()
        self._apply_collapse_state()
        self._save_state()
        if self.refresh_thread and self.refresh_thread.isRunning():
            self._refresh_pending = True
        else:
            self.refresh_data(force=True)

    def _setup_application_icon(self) -> None:
        icon = self._application_icon()
        QApplication.instance().setWindowIcon(icon)
        self.setWindowIcon(icon)

    def _create_menu(self) -> QMenu:
        menu = QMenu(self)
        show_action = menu.addAction("显示主窗口")
        hide_action = menu.addAction("隐藏主窗口")
        top_action = QAction("始终置顶", menu)
        top_action.setCheckable(True)
        top_action.setChecked(self.always_on_top)
        menu.addAction(top_action)
        menu.top_action = top_action
        menu.aboutToShow.connect(lambda: top_action.setChecked(self.always_on_top))
        menu.addSeparator()
        refresh_action = menu.addAction("立即刷新")
        menu.aboutToShow.connect(lambda: refresh_action.setEnabled(self.refresh_btn.isEnabled()))
        settings_action = menu.addAction("设置")
        menu.addSeparator()
        data_action = menu.addAction("打开数据文件夹")
        project_action = menu.addAction("打开项目文件夹")
        menu.addSeparator()
        exit_action = menu.addAction("退出程序")
        show_action.triggered.connect(self.show_and_activate)
        hide_action.triggered.connect(self.hide)
        refresh_action.triggered.connect(lambda: self.refresh_data(force=True))
        settings_action.triggered.connect(self.open_settings)
        data_action.triggered.connect(self.open_data_folder)
        project_action.triggered.connect(self.open_project_folder)
        top_action.triggered.connect(self.toggle_always_on_top)
        exit_action.triggered.connect(self.request_exit)
        return menu

    def _update_taskbar(self) -> None:
        visible = taskbar_provider_keys(self.config)
        freshness = compute_cache_freshness(
            str(self.last_updated_at) if self.last_updated_at else None
        )
        stale = freshness.status != "Fresh" or getattr(self, "_refresh_error", False)
        providers = self._taskbar_usage.get("providers", {})
        parts = []
        for key, name in (("codex", "Codex"), ("kimi", "Kimi"), ("deepseek", "DeepSeek"), ("aicodemirror", "AICodeMirror"), ("relayrouter", "RelayRouter")):
            if key not in visible:
                continue
            provider = providers.get(key, {})
            status = provider.get("status", "error")
            suffix = " [过期]" if stale or status != "ok" else ""
            if key in ("deepseek", "aicodemirror", "relayrouter"):
                balance = provider.get("balance") or {}
                value = balance.get("total")
                if isinstance(value, (int, float)):
                    parts.append(f"{name} {balance.get('currency') or ''} {value:.2f}{suffix}")
                else:
                    parts.append(f"{name} --")
                continue
            quotas = []
            for field, label in (("fiveHour", "5H"), ("weekly", "WEEK")):
                window = provider.get(field) or {}
                value = window.get("remainingPercent")
                if isinstance(value, (int, float)):
                    value = max(0, min(100, round(value)))
                    quotas.append(f"{label} {value}%")
                else:
                    quotas.append(f"{label} --")
            parts.append(f"{name} {' · '.join(quotas)}{suffix}")
        title = " | ".join(parts) or "暂无显示的数据源"
        if self.taskbar_strip is not None:
            self.taskbar_strip.update_quotas(
                {key: providers.get(key, {}) for key in ("codex", "kimi", "deepseek", "aicodemirror", "relayrouter") if key in visible},
                stale, self.config["ui"].get("theme") == "light",
                _localized_updated(self.last_updated_at).replace("更新于 ", "更新时间："))
        self.setWindowTitle(f"{self.config['ui'].get('title', 'Coding Energy')} | {title}")

    def _application_icon(self) -> QIcon:
        icon_path = application_icon_path()
        if icon_path.exists():
            icon = QIcon(str(icon_path))
            if not icon.isNull():
                return icon
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#26334f"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(2, 2, 60, 60, 14, 14)
        painter.setPen(QColor("#65d6a6"))
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(27)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "CP")
        painter.end()
        return QIcon(pixmap)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(1, 1, -1, -1), 13, 13)
        painter.fillPath(path, QColor("#f5f5f7" if self.config["ui"].get("theme") == "light" else "#111113"))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.globalPosition().toPoint()
            self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._is_dragging = False
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if not self._is_dragging and self._drag_start is not None:
                moved = (event.globalPosition().toPoint() - self._drag_start).manhattanLength()
                if moved > self._drag_threshold:
                    self._is_dragging = True
            self.move(event.globalPosition().toPoint() - self.drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.drag_offset = None
        if (
            not self._is_dragging
            and event.button() == Qt.MouseButton.LeftButton
            and self.collapsible
            and self.click_title_to_toggle
            and self.header_widget is not None
            and self.header_widget.geometry().contains(event.pos())
        ):
            self._toggle_collapse()
        self._is_dragging = False

    def _toggle_collapse(self) -> None:
        if not self.collapsible:
            return
        self.collapsed = not self.collapsed
        self._apply_collapse_state()
        self._save_state()

    def _apply_collapse_state(self, initial: bool = False) -> None:
        width = int(self.config["ui"].get("width", 280))
        if self.collapsed:
            self.setFixedWidth(width)
            self.cards_widget.hide()
            self.summary.show()
            self.updated.hide()
            self.collapse_btn.setText("˅")
            self.setFixedHeight(self.collapsed_height)
            self.resize(width, self.collapsed_height)
        else:
            self.cards_widget.show()
            self.summary.hide()
            self.updated.show()
            self.collapse_btn.setText("˄")
            self.setMaximumSize(16777215, 16777215)
            self.setMinimumSize(0, 0)
            self.setFixedWidth(width)
            self.layout().activate()
            self.resize(width, max(self.expanded_height, self.sizeHint().height()))
        self._update_summary()

    def _update_summary(self) -> None:
        usage = read_usage(self.cache_path, create_if_missing=True)
        providers = usage.get("providers", {})
        show_reset = (
            self.config["ui"].get("show_reset_times", True)
            and self.config["ui"].get("compact_summary_show_reset", True)
        )
        visible = self.config["ui"].get("visible_providers", ["codex", "kimi", "deepseek"])
        text = _format_compact_summary({key: value for key, value in providers.items() if key in visible}, show_reset=show_reset)
        freshness = compute_cache_freshness(
            str(usage.get("updatedAt")) if usage.get("updatedAt") else None
        )
        lines = text.splitlines()
        if lines:
            state = {"Fresh": "已同步", "Stale": "数据陈旧", "Expired": "已过期", "Unknown": "尚未同步"}[freshness.status]
            lines[-1] = f"{lines[-1]}  {state}"
        self.summary.setText("\n".join(lines))
        if self.collapsed and "\n" in self.summary.text():
            new_height = max(self.collapsed_height, 78)
            self.setFixedHeight(new_height)
            self.resize(self.width(), new_height)
        elif self.collapsed:
            self.setFixedHeight(self.collapsed_height)
            self.resize(self.width(), self.collapsed_height)

    def contextMenuEvent(self, event) -> None:
        self._show_context_menu(event.globalPos())

    def _show_context_menu(self, position: QPoint) -> None:
        menu = self._create_menu()
        menu.exec(position)
        menu.deleteLater()

    def refresh_data(self, force=False) -> None:
        if self.refresh_thread and self.refresh_thread.isRunning():
            return
        self._refresh_error = False
        self.updated.setText("正在刷新…")
        if self.collapsed:
            self.summary.setText("正在刷新…")
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("...")
        self.refresh_thread = RefreshThread(self.project_root, self.config, force=force)
        self.refresh_thread.completed.connect(self.load_cache)
        self.refresh_thread.failed.connect(self._refresh_failed)
        self.refresh_thread.finished.connect(self._refresh_finished)
        self.refresh_thread.start()

    def _refresh_failed(self, message: str) -> None:
        self._refresh_error = True
        self._update_taskbar()
        self.updated.setText("刷新失败 · 保留上次数据")
        self.updated.setToolTip(sanitize_message(message, 120))
        if self.collapsed:
            self.summary.setText("刷新失败 · 保留上次数据")

    def _refresh_finished(self) -> None:
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("刷新")
        thread = self.refresh_thread
        self.refresh_thread = None
        if thread is not None:
            thread.deleteLater()
        if not getattr(self, "_refresh_error", False):
            self._update_freshness()
        if self.exit_requested:
            self._finish_exit()
        elif self._refresh_pending:
            self._refresh_pending = False
            self.refresh_data(force=True)

    def load_cache(self) -> None:
        usage = read_usage(self.cache_path, create_if_missing=True)
        self._taskbar_usage = usage
        providers = usage.get("providers", {})
        codex = providers.get("codex", {})
        kimi = providers.get("kimi", {})
        deepseek = providers.get("deepseek", {})
        self.codex_card.update_data(codex)
        self.kimi_card.update_data(kimi)
        self.deepseek_card.update_data(deepseek)
        self.aicodemirror_card.update_data(providers.get("aicodemirror", {}))
        self.relayrouter_card.update_data(providers.get("relayrouter", {}))
        visible = self.config["ui"].get("visible_providers", ["codex", "kimi", "deepseek"])
        values = _remaining_values(tuple(providers.get(key, {}) for key in ("codex", "kimi") if key in visible))
        self.face.setText(_face(min(values) if values else None))
        self.last_updated_at = usage.get("updatedAt")
        self._update_taskbar()
        self._update_summary()
        self._update_freshness()
        self._apply_collapse_state()

    def _update_freshness(self) -> None:
        self._update_taskbar()
        if self.refresh_thread and self.refresh_thread.isRunning():
            return
        freshness = compute_cache_freshness(
            str(self.last_updated_at) if self.last_updated_at else None
        )
        if getattr(self, "_refresh_error", False):
            self.updated.setText("刷新失败 · 保留上次数据")
            return
        self.updated.setToolTip("")
        self.updated.setText(_localized_updated(self.last_updated_at))
        color = COLOR_DANGER if freshness.status == "Expired" else COLOR_MUTED
        self.updated.setStyleSheet(f"color: {color};")
        if self.collapsed:
            self._update_summary()

    def toggle_always_on_top(self) -> None:
        position = self.pos()
        self.always_on_top = not self.always_on_top
        self._apply_flags()
        self.move(position)
        self.show()
        self._save_state()

    def open_data_folder(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._open_folder(self.cache_path.parent, "data")

    def open_project_folder(self) -> None:
        self._open_folder(self.project_root, "project")

    def _open_folder(self, path: Path, label: str) -> None:
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError:
            self.updated.setText("无法打开文件夹")

    def closeEvent(self, event) -> None:
        self._save_state()
        if self.taskbar_strip is not None and self.taskbar_strip.isVisible() and not self.exit_requested:
            self.hide()
            event.ignore()
            return
        self.request_exit()
        event.accept()

    def show_and_activate(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def request_exit(self) -> None:
        if self.exit_requested:
            return
        self.exit_requested = True
        self.timer.stop()
        self.freshness_timer.stop()
        if self.taskbar_strip is not None:
            self.taskbar_strip.close()
        self._save_state()
        self.hide()
        if self.refresh_thread and self.refresh_thread.isRunning():
            self.refresh_thread.requestInterruption()
            return
        self._finish_exit()

    def _finish_exit(self) -> None:
        QApplication.quit()

    def _restore_position(self, state: dict[str, Any]) -> None:
        x = state.get("x")
        y = state.get("y")
        if not isinstance(x, int) or not isinstance(y, int):
            return
        target = QRect(QPoint(x, y), self.size())
        screens = QApplication.screens()
        if any(screen.availableGeometry().intersects(target) for screen in screens):
            self.move(x, y)

    def _save_state(self) -> None:
        try:
            write_ui_state(
                self.state_path,
                {
                    "x": self.x(),
                    "y": self.y(),
                    "always_on_top": self.always_on_top,
                    "collapsed": self.collapsed,
                    "taskbar_offset": self.taskbar_strip.offset if self.taskbar_strip is not None else 0,
                },
            )
        except OSError:
            pass

    def _save_taskbar_offset(self, offset: int) -> None:
        self._save_state()


def run_widget(project_root: Path | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    # closeEvent and the shared menu control shutdown, including worker cleanup.
    app.setQuitOnLastWindowClosed(False)
    widget = CodingPlanWidget(project_root)
    widget.show()
    return app.exec()


def _remaining_values(providers: tuple[dict[str, Any], ...]) -> list[int]:
    values: list[int] = []
    for provider in providers:
        for key in ("fiveHour", "weekly"):
            window = provider.get(key, {})
            value = window.get("remainingPercent") if isinstance(window, dict) else None
            if isinstance(value, (int, float)):
                values.append(round(value))
    return values


def _format_compact_summary(providers: dict[str, Any], show_reset: bool = True) -> str:
    codex = providers.get("codex", {})
    kimi = providers.get("kimi", {})
    deepseek = providers.get("deepseek", {})

    def pct(window: Any) -> str:
        if isinstance(window, dict) and window.get("remainingPercent") is not None:
            return f"{round(window['remainingPercent'])}"
        return "--"

    def provider_summary(provider: dict[str, Any], prefix: str) -> str:
        if provider.get("status") != "ok":
            return f"{prefix} 离线"
        five = provider.get("fiveHour", {})
        weekly = provider.get("weekly", {})
        return f"{prefix} {pct(five)}/{pct(weekly)}"

    parts = [provider_summary(providers[key], label) for key, label in (("codex", "C"), ("kimi", "K")) if key in providers]

    balance = deepseek.get("balance") or {}
    if "deepseek" not in providers:
        pass
    elif deepseek.get("status") == "ok" and balance.get("total") is not None:
        parts.append(f"DS {float(balance['total']):.2f}")
    else:
        parts.append("DS 离线")

    if "aicodemirror" in providers:
        mirror = providers["aicodemirror"]
        balance = mirror.get("balance") or {}
        if balance.get("total") is not None:
            parts.append(f"ACM {balance['total']:.2f}" + (" 过期" if mirror.get("status") != "ok" else ""))
        else:
            parts.append("ACM --")

    if "relayrouter" in providers:
        relay = providers["relayrouter"]
        balance = relay.get("balance") or {}
        value = balance.get("total")
        parts.append((f"RR ${value:.2f}" + (" 过期" if relay.get("status") != "ok" else "")) if value is not None else "RR --")

    summary = "  ".join(parts) or "暂无显示的数据源"

    if not show_reset:
        return summary

    reset_parts = []
    for label, provider in (("C", codex), ("K", kimi)):
        if provider.get("status") != "ok":
            continue
        five = provider.get("fiveHour", {})
        if isinstance(five, dict):
            reset = format_reset_time(five.get("resetAt"))
            if reset != "--":
                reset_parts.append(f"{label}{reset}")
    if not reset_parts:
        return summary
    return f"{summary}\nR {' '.join(reset_parts)}"


def _summary_pct(window: Any) -> str:
    if isinstance(window, dict) and window.get("remainingPercent") is not None:
        return f"{round(window['remainingPercent'])}"
    return "--"


def _face(value: int | None) -> str:
    if value is None:
        return "(?_?)"
    if value >= 50:
        return "(^_^)"
    if value >= 30:
        return "(-_-)"
    if value >= 15:
        return "(>_<)"
    return "(x_x)"


def _quota_color(value: Any, status: str) -> str:
    if status != "ok" or not isinstance(value, (int, float)):
        return COLOR_MUTED
    if value >= 30:
        return COLOR_NORMAL
    if value >= 15:
        return COLOR_WARNING
    return COLOR_DANGER
