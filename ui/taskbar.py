"""A compact quota strip positioned over the Windows taskbar beside the tray."""

from __future__ import annotations

import ctypes
import os
import math
from ctypes import wintypes
from pathlib import Path
import sys

from PySide6.QtCore import QElapsedTimer, QPoint, QRectF, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QToolTip, QWidget

from core.time_display import format_reset_time


def quota_percent(window):
    value = window.get("remainingPercent") if isinstance(window, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return max(0, min(100, value))


def logo_path(key: str, light: bool) -> Path:
    name = "kimi-dark" if key == "kimi" and not light else key
    relative = Path("assets") / "quotabar" / f"{name}.{'ico' if key == 'aicodemirror' else 'png'}"
    external = Path(sys.executable).resolve().parent / relative if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1] / relative
    if external.exists():
        return external
    return Path(getattr(sys, "_MEIPASS", external.parent)) / relative


class QuotaRing(QWidget):
    """Brand mark inside weekly (middle) and five-hour (outer) quota rings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 40)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.key = ""
        self.weekly = self.five_hour = None
        self.stale = False
        self.light = False
        self.logo = QPixmap()

    def set_reading(self, key, data, stale, light):
        self.key = key
        self.weekly = quota_percent(data.get("weekly"))
        self.five_hour = quota_percent(data.get("fiveHour"))
        self.stale = stale or data.get("status") != "ok"
        if self.logo.isNull() or self.property("logo_key") != (key, light):
            self.logo = QIcon(str(logo_path(key, light))).pixmap(64, 64)
            self.setProperty("logo_key", (key, light))
        self.light = light
        name = {"codex": "Codex", "kimi": "Kimi", "deepseek": "DeepSeek", "aicodemirror": "AICodeMirror", "relayrouter": "RelayRouter"}.get(key, key)
        def percent(value):
            return "--" if value is None else f"{value:g}%"
        description = name
        for field, label, value in (("fiveHour", "5 小时", self.five_hour),
                                    ("weekly", "每周", self.weekly)):
            window = data.get(field) or {}
            reset = format_reset_time(window.get("resetAt")) if isinstance(window, dict) else "--"
            if reset == "soon":
                reset = "即将重置"
            description += f"\n{label}剩余量：{percent(value)} · 重置时间：{reset}"
        if key in ("deepseek", "aicodemirror", "relayrouter"):
            balance = data.get("balance") or {}
            description = f"{name}\n剩余余额：{balance.get('currency') or ''} {balance.get('total', '--')}\n重置时间：不适用（无周/5H限额）"
        if self.stale:
            description += "（数据过期或刷新失败）"
        self.setAccessibleName(description)
        self.update()

    def ring_color(self, value, weekly=False):
        if self.stale or value is None:
            return QColor("#87909f")
        if value < 15:
            return QColor("#ff5c5c")
        if value < 30:
            return QColor("#ffbb55")
        return QColor("#6c96f5" if weekly else "#3dd68c")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        painter.scale(self.width() / 64, self.height() / 64)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for bounds, value, weekly in ((QRectF(5, 5, 54, 54), self.five_hour, False),
                                       (QRectF(11, 11, 42, 42), self.weekly, True)):
            painter.setPen(QPen(QColor("#d0d6df" if self.light else "#343434"), 3.5))
            painter.drawEllipse(bounds)
            if value is not None and value > 0:
                pen = QPen(self.ring_color(value, weekly), 3.5)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                # Qt's negative sweep is clockwise, starting at twelve o'clock.
                painter.drawArc(bounds, 90 * 16, -round(value / 100 * 360 * 16))
        if not self.logo.isNull():
            painter.setOpacity(0.55 if self.stale else 1.0)
            size = self.logo.size().scaled(QSize(29, 29), Qt.AspectRatioMode.KeepAspectRatio)
            painter.drawPixmap(QRectF((64-size.width())/2, (64-size.height())/2, size.width(), size.height()),
                               self.logo, QRectF(self.logo.rect()))
        else:
            painter.setPen(QColor("#87909f"))
            painter.drawText(QRectF(17, 17, 30, 30), Qt.AlignmentFlag.AlignCenter, "?")


def taskbar_bounds():
    """Return native pixel rectangles; no Explorer handles are retained."""
    if os.name != "nt":
        return None
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowExW.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    user32.GetDpiForWindow.restype = wintypes.UINT
    taskbar = user32.FindWindowW("Shell_TrayWnd", None)
    rect = wintypes.RECT()
    if not taskbar or not user32.IsWindowVisible(taskbar) or not user32.GetWindowRect(taskbar, ctypes.byref(rect)):
        return None
    tray = user32.FindWindowExW(taskbar, None, "TrayNotifyWnd", None)
    tray_rect = wintypes.RECT()
    if not tray or not user32.GetWindowRect(tray, ctypes.byref(tray_rect)):
        return None
    return taskbar, rect, tray_rect, (user32.GetDpiForWindow(taskbar) or 96) / 96


def strip_geometry(bar, tray, width: int, height: int, offset: int, gap: int):
    """Place before the notification area and clamp dragging to the taskbar."""
    if bar.right - bar.left < bar.bottom - bar.top:
        return None  # Vertical taskbars need a separate layout.
    right = min(bar.right, tray.left) - gap
    if width > right - bar.left - gap or width < 24 or bar.bottom - bar.top < height:
        return None
    x = max(bar.left + gap, min(right - width, right - width - offset))
    return x, bar.top + (bar.bottom - bar.top - height) // 2, width, height


class TaskbarQuotaStrip(QWidget):
    restore_requested = Signal()
    offset_changed = Signal(int)
    context_menu_requested = Signal(QPoint)

    def __init__(self, offset: int = 0):
        super().__init__()
        self.offset = max(0, offset) if isinstance(offset, int) else 0
        self._drag_start = None
        self._drag_offset = 0
        self._dragged = False
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # This strip never takes focus; Qt otherwise suppresses its tooltips.
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
        self.setWindowTitle("Coding Energy 任务栏额度")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(4)
        self.rings = []
        for _ in range(5):
            ring = QuotaRing(self)
            layout.addWidget(ring)
            self.rings.append(ring)
        self.setToolTip("暂无额度数据")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.reposition)
        self.timer.start(1000)
        # Windows can route mouse events through fully transparent pixels.
        # Check the whole strip so hovering between the rings also works.
        self._hover_elapsed = QElapsedTimer()
        self._tooltip_shown = False
        self.hover_timer = QTimer(self)
        self.hover_timer.timeout.connect(self._check_hover)
        self.hover_timer.start(100)

    def _check_hover(self):
        position = QCursor.pos()
        hovering = (self.isVisible() and self._drag_start is None
                    and self.rect().contains(self.mapFromGlobal(position)))
        if not hovering:
            self._reset_hover()
            return
        if not self._hover_elapsed.isValid():
            self._hover_elapsed.start()
        elif self._hover_elapsed.elapsed() >= 500 and not self._tooltip_shown:
            QToolTip.showText(position, self.toolTip(), self)
            self._tooltip_shown = True

    def _reset_hover(self):
        self._hover_elapsed.invalidate()
        if self._tooltip_shown:
            QToolTip.hideText()
            self._tooltip_shown = False

    def hideEvent(self, event):
        self._reset_hover()
        super().hideEvent(event)

    def update_quotas(self, providers: dict, stale: bool, light: bool, updated_text: str = "更新时间：--"):
        items = list(providers.items())[:len(self.rings)]
        for index, ring in enumerate(self.rings):
            ring.setVisible(index < len(items))
            if index < len(items):
                key, data = items[index]
                ring.set_reading(key, data, stale, light)
        self.setToolTip("\n".join(
            [ring.accessibleName() for ring in self.rings[:len(items)]] + [updated_text]))
        self._has_data = bool(items)
        self.reposition()

    def reposition(self):
        bounds = taskbar_bounds()
        if not getattr(self, "_has_data", False) or bounds is None:
            self.hide()
            return
        taskbar, bar, tray, scale = bounds
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HANDLE

        class MonitorInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        monitor = MonitorInfo()
        monitor.cbSize = ctypes.sizeof(monitor)
        if not user32.GetMonitorInfoW(user32.MonitorFromWindow(taskbar, 2), ctypes.byref(monitor)):
            self.hide()
            return
        screen = monitor.rcMonitor
        # Auto-hidden taskbars can remain "visible" while located off screen.
        visible_height = min(bar.bottom, screen.bottom) - max(bar.top, screen.top)
        if visible_height < (bar.bottom - bar.top) / 2:
            self.hide()
            return
        foreground = user32.GetForegroundWindow()
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        class_name = ctypes.create_unicode_buffer(256)
        if foreground:
            user32.GetClassNameW(foreground, class_name, len(class_name))
        front = wintypes.RECT()
        if foreground and class_name.value not in ("Progman", "WorkerW") and foreground not in (taskbar, int(self.winId())) and user32.GetWindowRect(foreground, ctypes.byref(front)):
            if front.left <= screen.left and front.top <= screen.top and front.right >= screen.right and front.bottom >= screen.bottom:
                self.hide()
                return
        # Keep both rings inside short taskbars at 125/150/200% display scaling.
        diameter = max(16, min(40, int((bar.bottom - bar.top) / scale) - 4))
        for ring in self.rings:
            ring.setFixedSize(diameter, diameter)
        hint = self.sizeHint()
        geometry = strip_geometry(bar, tray, round(hint.width() * scale),
                                  round(hint.height() * scale),
                                  round(self.offset * scale), round(6 * scale))
        if geometry is None:
            self.hide()
            return
        self.show()
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        # Native pixel placement avoids mixing Qt logical and Win32 physical coordinates.
        user32.SetWindowPos(int(self.winId()), -1, *geometry, 0x0010)  # SWP_NOACTIVATE

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.globalPosition().toPoint()
            self._drag_offset = self.offset
            self._dragged = False

    def mouseMoveEvent(self, event):
        if self._drag_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint().x() - self._drag_start.x()
            if abs(delta) > 4:
                self._dragged = True
            if self._dragged:
                self.offset = max(0, self._drag_offset - delta)
                self.reposition()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_start is not None:
            if self._dragged:
                self.offset_changed.emit(self.offset)
            else:
                self.restore_requested.emit()
            self._drag_start = None

    def closeEvent(self, event):
        self.timer.stop()
        self.hover_timer.stop()
        self._reset_hover()
        super().closeEvent(event)

    def contextMenuEvent(self, event):
        self.context_menu_requested.emit(event.globalPos())
        event.accept()
