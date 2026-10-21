"""Settings editor; changes are committed only after validation and Save."""
from copy import deepcopy
from urllib.parse import urlparse

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QGroupBox, QLabel, QLineEdit, QMessageBox,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from core.settings import save_config
from core.security import sanitize_message


class SettingsDialog(QDialog):
    def __init__(self, root, config, parent=None):
        super().__init__(parent)
        self.root = root
        self.config = deepcopy(config)
        self.setWindowTitle("设置 · Coding Plan")
        self.resize(540, 580)
        self.setStyleSheet('''
            QDialog, QWidget { background: #171e2d; color: #e7edf8; font-size: 13px; }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #242f44; padding: 6px; border: 1px solid #40516b; border-radius: 5px; }
            QPushButton { background: #334867; padding: 7px 16px; border-radius: 5px; }
            QGroupBox { border: 1px solid #40516b; border-radius: 6px; margin-top: 15px; padding-top: 14px; }
            QTabBar::tab { padding: 10px 20px; } QTabBar::tab:selected { background: #334867; }
        ''')
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        display = QWidget()
        form = QFormLayout(display)
        ui = config['ui']
        self.title_edit = QLineEdit(ui.get('title', 'Coding Energy'))
        self.title_edit.setMaxLength(40)
        form.addRow('窗口标题', self.title_edit)
        self.theme = QComboBox()
        self.theme.addItems(['dark', 'light'])
        self.theme.setCurrentText(ui.get('theme', 'dark'))
        form.addRow('配色主题', self.theme)
        self.width_input = self.spin(form, '窗口宽度 (px)', ui.get('width', 340), 320, 640)
        self.height_input = self.spin(form, '展开最小高度 (px)', ui.get('expanded_height', 360), 240, 900)
        self.opacity = QDoubleSpinBox()
        self.opacity.setRange(.4, 1.)
        self.opacity.setSingleStep(.05)
        self.opacity.setValue(ui.get('opacity', .92))
        form.addRow('窗口不透明度', self.opacity)
        self.top = self.check(form, '始终置顶', ui.get('always_on_top', True))
        self.collapse = self.check(form, '允许折叠窗口', ui.get('collapsible', True))
        self.reset = self.check(form, '显示重置时间', ui.get('show_reset_times', True))
        self.compact_reset = self.check(form, '折叠摘要显示重置时间', ui.get('compact_summary_show_reset', True))
        self.interval = self.spin(form, '自动刷新间隔 (秒)', config['app'].get('refresh_interval_seconds', 180), 30, 86400)
        self.timeout = self.spin(form, '采集超时 (秒)', config['provider'].get('timeout_seconds', 15), 1, 120)
        tabs.addTab(display, '界面与刷新')
        providers = QWidget()
        provider_layout = QVBoxLayout(providers)
        note = QLabel('显示控制卡片和折叠摘要；启用采集控制网络请求。\nAPI Key 请在项目 .env 或环境变量中配置。')
        note.setWordWrap(True)
        provider_layout.addWidget(note)
        self.enabled = {}
        self.visible = {}
        visible = ui.get('visible_providers', ['codex', 'kimi', 'deepseek'])
        for key, label in [('codex', 'Codex'), ('kimi', 'Kimi'), ('deepseek', 'DeepSeek')]:
            group = QGroupBox(label)
            rows = QFormLayout(group)
            self.visible[key] = self.check(rows, '在界面显示', key in visible)
            self.enabled[key] = self.check(rows, '启用数据采集', config[key].get('enabled', True))
            if key == 'codex':
                self.mode = QComboBox()
                self.mode.addItems(['auto', 'official_oauth', 'custom_command'])
                self.mode.setCurrentText(config[key].get('mode', 'auto'))
                rows.addRow('采集模式', self.mode)
                self.codex_command = QLineEdit(config[key].get('custom_command', ''))
                self.codex_command.setPlaceholderText('自定义命令（输出 JSON）')
                rows.addRow('自定义命令', self.codex_command)
            elif key == 'kimi':
                self.kimi_command = QLineEdit(config[key].get('command', 'kimi-usage --json'))
                rows.addRow('采集命令', self.kimi_command)
            else:
                self.balance_url = QLineEdit(config[key].get('balance_url', 'https://api.deepseek.com/user/balance'))
                rows.addRow('余额接口 (HTTPS)', self.balance_url)
                self.currency = QComboBox()
                self.currency.setEditable(True)
                self.currency.addItems(['', 'CNY', 'USD'])
                self.currency.setCurrentText(config[key].get('preferred_currency', ''))
                rows.addRow('首选币种（空为自动）', self.currency)
            provider_layout.addWidget(group)
        tabs.addTab(providers, '模型 / 数据源')
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def spin(form, title, value, low, high):
        widget = QSpinBox()
        widget.setRange(low, high)
        widget.setValue(int(value))
        form.addRow(title, widget)
        return widget

    @staticmethod
    def check(form, title, value):
        widget = QCheckBox(title)
        widget.setChecked(bool(value))
        form.addRow(widget)
        return widget

    def save(self):
        command = self.codex_command.text().strip()
        url = self.balance_url.text().strip()
        if self.enabled['codex'].isChecked() and self.mode.currentText() == 'custom_command' and not command:
            QMessageBox.warning(self, '配置不完整', '请填写 Codex 自定义命令。')
            return
        if self.enabled['kimi'].isChecked() and not self.kimi_command.text().strip():
            QMessageBox.warning(self, '配置不完整', '请填写 Kimi 采集命令。')
            return
        parsed = urlparse(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            QMessageBox.warning(self, '接口地址无效', '请输入不含用户名和密码的 HTTPS 接口地址。')
            return
        ui = self.config['ui']
        ui.update(title=self.title_edit.text().strip() or 'Coding Energy', theme=self.theme.currentText(),
                  width=self.width_input.value(), expanded_height=self.height_input.value(),
                  opacity=self.opacity.value(), always_on_top=self.top.isChecked(),
                  collapsible=self.collapse.isChecked(), show_reset_times=self.reset.isChecked(),
                  compact_summary_show_reset=self.compact_reset.isChecked(),
                  visible_providers=[key for key, check in self.visible.items() if check.isChecked()])
        self.config['app']['refresh_interval_seconds'] = self.interval.value()
        self.config['provider']['timeout_seconds'] = self.timeout.value()
        for key, check in self.enabled.items():
            self.config[key]['enabled'] = check.isChecked()
        self.config['codex'].update(mode=self.mode.currentText(), custom_command=command)
        self.config['kimi']['command'] = self.kimi_command.text().strip()
        self.config['deepseek'].update(balance_url=url, preferred_currency=self.currency.currentText().strip().upper())
        try:
            save_config(self.root, self.config)
        except OSError as exc:
            QMessageBox.warning(self, '保存失败', sanitize_message(exc))
            return
        self.accept()
