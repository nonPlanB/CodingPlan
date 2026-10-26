"""Settings editor; changes are committed only after validation and Save."""
from copy import deepcopy
from urllib.parse import urlparse
import subprocess

from PySide6.QtCore import QTimer, QThread, Signal

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QGroupBox, QLabel, QLineEdit, QMessageBox,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget, QPushButton, QScrollArea)

from core.settings import save_config
from core.security import sanitize_message
from core.provider_visibility import taskbar_provider_keys
from core.aicodemirror_session import clear_session, session_path
from providers.aicodemirror_provider import browser_command, parse_helper_output
from core.relayrouter_credentials import (load_credentials, save_credentials, clear_credentials,
                                         validate_credentials)
from providers.relayrouter_provider import query_balance


class RelayConnectionTest(QThread):
    completed = Signal(dict)

    def __init__(self, credentials, timeout, use_system_proxy, parent=None):
        super().__init__(parent)
        self.credentials = credentials
        self.timeout = timeout
        self.use_system_proxy = use_system_proxy

    def run(self):
        try:
            reading = query_balance(self.credentials, self.timeout, self.use_system_proxy)
        except Exception:
            reading = {"status": "error", "message": "连接测试未完成，请检查网络和凭据。"}
        finally:
            self.credentials = None
        self.completed.emit(reading)


class SettingsDialog(QDialog):
    def __init__(self, root, config, parent=None):
        super().__init__(parent)
        self.root = root
        self.config = deepcopy(config)
        self.login_process = None
        self.relay_test_thread = None
        self.login_timer = QTimer(self)
        self.login_timer.timeout.connect(self._check_login)
        self.setWindowTitle("设置 · Coding Plan")
        self.resize(540, 580)
        self._apply_theme(config['ui'].get('theme', 'dark'))
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
        self.theme.addItem('深色', 'dark')
        self.theme.addItem('浅色', 'light')
        self.theme.setCurrentIndex(max(0, self.theme.findData(ui.get('theme', 'dark'))))
        self.theme.currentIndexChanged.connect(lambda: self._apply_theme(self.theme.currentData()))
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
        note = QLabel('主界面和任务栏可独立选择显示；只有启用采集的数据源可在任务栏显示。\nAPI Key 请在项目 .env 或环境变量中配置。')
        note.setWordWrap(True)
        provider_layout.addWidget(note)
        self.enabled = {}
        self.visible = {}
        self.taskbar_visible = {}
        visible = ui.get('visible_providers', ['codex', 'kimi', 'deepseek'])
        taskbar_selected = ui.get('taskbar_providers')
        if taskbar_selected is None:
            taskbar_selected = taskbar_provider_keys(config)
        for key, label in [('codex', 'Codex'), ('kimi', 'Kimi'), ('deepseek', 'DeepSeek'), ('aicodemirror', 'AICodeMirror'), ('relayrouter', 'RelayRouter')]:
            group = QGroupBox(label)
            rows = QFormLayout(group)
            self.visible[key] = self.check(rows, '在界面显示', key in visible)
            self.enabled[key] = self.check(rows, '启用数据采集', config[key].get('enabled', True))
            self.taskbar_visible[key] = self.check(rows, '在任务栏显示', key in taskbar_selected)
            self.taskbar_visible[key].setEnabled(self.enabled[key].isChecked())
            self.enabled[key].toggled.connect(self.taskbar_visible[key].setEnabled)
            if key == 'codex':
                self.mode = QComboBox()
                for name, value in [('自动选择', 'auto'), ('官方 OAuth 登录', 'official_oauth'), ('自定义命令', 'custom_command')]:
                    self.mode.addItem(name, value)
                self.mode.setCurrentIndex(max(0, self.mode.findData(config[key].get('mode', 'auto'))))
                rows.addRow('采集模式', self.mode)
                self.codex_command = QLineEdit(config[key].get('custom_command', ''))
                self.codex_command.setPlaceholderText('自定义命令（输出 JSON）')
                rows.addRow('自定义命令', self.codex_command)
            elif key == 'kimi':
                self.kimi_command = QLineEdit(config[key].get('command', 'kimi-usage --json'))
                rows.addRow('采集命令', self.kimi_command)
            elif key == 'deepseek':
                self.balance_url = QLineEdit(config[key].get('balance_url', 'https://api.deepseek.com/user/balance'))
                rows.addRow('余额接口 (HTTPS)', self.balance_url)
                self.currency = QComboBox()
                self.currency.setEditable(True)
                self.currency.addItems(['', 'CNY', 'USD'])
                self.currency.setCurrentText(config[key].get('preferred_currency', ''))
                rows.addRow('首选币种（空为自动）', self.currency)
            elif key == 'aicodemirror':
                self.login_status = QLabel('已有加密会话；余额刷新会验证有效性。' if session_path(root).exists() else '尚未登录。')
                self.login_status.setWordWrap(True)
                rows.addRow(self.login_status)
                self.login_button = QPushButton('登录 / 重新登录 AICodeMirror')
                self.login_button.clicked.connect(self._login)
                rows.addRow(self.login_button)
                self.logout_button = QPushButton('退出并清除本地登录')
                self.logout_button.clicked.connect(self._logout)
                rows.addRow(self.logout_button)
                self.mirror_timeout = self.spin(rows, '浏览器查询超时 (秒)', config[key].get('browser_timeout_seconds', 45), 15, 120)
            else:
                self.relay_id = QLineEdit()
                self.relay_id.setMaxLength(16)
                self.relay_token = QLineEdit()
                self.relay_token.setEchoMode(QLineEdit.EchoMode.Password)
                self.relay_token.setMaxLength(4096)
                self.relay_token.setPlaceholderText('输入新令牌；已保存时留空保留原令牌')
                rows.addRow('用户 ID', self.relay_id)
                rows.addRow('身份验证令牌', self.relay_token)
                self.relay_status = QLabel()
                self.relay_status.setWordWrap(True)
                rows.addRow(self.relay_status)
                self._reload_relay_credentials()
                self.relay_save = QPushButton('保存凭据（立即生效）')
                self.relay_save.clicked.connect(self._save_relay_credentials)
                rows.addRow(self.relay_save)
                self.relay_test = QPushButton('测试连接')
                self.relay_test.clicked.connect(self._test_relay_connection)
                rows.addRow(self.relay_test)
                self.relay_clear = QPushButton('清除凭据（立即生效）')
                self.relay_clear.clicked.connect(self._clear_relay_credentials)
                rows.addRow(self.relay_clear)
                self.relay_interval = self.spin(rows, '查询最小间隔 (秒)', config[key].get('refresh_interval_seconds', 300), 30, 86400)
                self.relay_proxy = self.check(rows, '使用系统代理', config[key].get('use_system_proxy', False))
                description = QLabel('凭据独立加密保存；下方保存按钮保存显示和采集选项。\n更换用户 ID 时请同时提供新令牌。测试连接不保存输入。')
                description.setWordWrap(True)
                rows.addRow(description)
            provider_layout.addWidget(group)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(providers)
        tabs.addTab(scroll, '模型 / 数据源')
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _login(self):
        if self.login_process is not None:
            return
        try:
            self.login_process = subprocess.Popen(browser_command(self.root, 'login'),
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except OSError:
            self.login_status.setText('无法启动登录窗口，请检查浏览器组件。')
            return
        self.login_button.setEnabled(False)
        self.logout_button.setEnabled(False)
        self.login_status.setText('请在独立的官方登录窗口完成登录，然后点击保存并关闭。')
        self.login_timer.start(500)

    def _reload_relay_credentials(self):
        try:
            stored = load_credentials(self.root)
        except ValueError:
            stored = None
            self.relay_status.setText('加密凭据无法读取，请重新保存或清除。')
        else:
            self.relay_status.setText('令牌已加密保存；留空保留原令牌。' if stored else '尚未配置凭据。')
        self.relay_saved_id = stored['user_id'] if stored else ''
        self.relay_id.setText(self.relay_saved_id)
        self.relay_token.clear()

    def _relay_candidate(self):
        user_id, entered = self.relay_id.text().strip(), self.relay_token.text().strip()
        if not entered:
            stored = load_credentials(self.root)
            if not stored or stored['user_id'] != user_id:
                raise ValueError('首次配置或更换用户 ID 时，请输入对应的身份验证令牌。')
            entered = stored['access_token']
        return validate_credentials(user_id, entered)

    def _save_relay_credentials(self):
        try:
            values = self._relay_candidate()
            save_credentials(self.root, **values)
        except (OSError, ValueError):
            self.relay_status.setText('保存失败：请检查用户 ID、令牌及数据目录权限；更换 ID 需同时输入新令牌。')
            return
        self._reload_relay_credentials()
        self.relay_status.setText('凭据已加密保存。可测试连接，然后保存显示和采集选项。')

    def _clear_relay_credentials(self):
        try:
            clear_credentials(self.root)
        except OSError:
            self.relay_status.setText('清除失败，请检查数据目录权限。')
            return
        self._reload_relay_credentials()
        self.relay_status.setText('已清除本地凭据和缓存余额。')

    def _test_relay_connection(self):
        if self.relay_test_thread is not None:
            return
        try:
            values = self._relay_candidate()
        except ValueError as exc:
            self.relay_status.setText(str(exc))
            return
        self.relay_status.setText('正在测试连接…')
        for field in (self.relay_id, self.relay_token, self.relay_save, self.relay_test, self.relay_clear):
            field.setEnabled(False)
        self.relay_test_thread = RelayConnectionTest(values, self.timeout.value(), self.relay_proxy.isChecked(), self)
        self.relay_test_thread.completed.connect(self._relay_test_result)
        self.relay_test_thread.finished.connect(self._relay_test_finished)
        self.relay_test_thread.start()

    def _relay_test_result(self, reading):
        if reading.get('status') == 'ok':
            self.relay_status.setText('连接成功，账户余额 ' + reading['balance']['display'] + '。测试未保存输入。')
        else:
            self.relay_status.setText(reading.get('message') or '连接失败。')

    def _relay_test_finished(self):
        thread = self.relay_test_thread
        self.relay_test_thread = None
        if thread is not None:
            thread.deleteLater()
        for field in (self.relay_id, self.relay_token, self.relay_save, self.relay_test, self.relay_clear):
            field.setEnabled(True)

    def _check_login(self):
        if self.login_process is None or self.login_process.poll() is None:
            return
        output, _ = self.login_process.communicate()
        self.login_process = None
        self.login_timer.stop()
        self.login_button.setEnabled(True)
        self.logout_button.setEnabled(True)
        reading = parse_helper_output(output.decode('utf-8', errors='replace'))
        if reading['status'] == 'ok':
            self.login_status.setText('会话已加密保存。保存设置后会在独立进程中验证恢复并刷新余额。')
            self.enabled['aicodemirror'].setChecked(True)
            self.visible['aicodemirror'].setChecked(True)
        else:
            self.login_status.setText(reading.get('message') or '尚未完成登录。')

    def _logout(self):
        try:
            clear_session(self.root)
        except OSError as exc:
            self.login_status.setText(sanitize_message(exc))
            return
        self.login_status.setText('已清除本机登录和缓存余额。网站端会话如需撤销，请到官网操作。')

    def done(self, code):
        if self.login_process is not None:
            self.login_status.setText('请先关闭独立登录窗口，再保存或取消设置。')
            return
        if self.relay_test_thread is not None:
            self.relay_status.setText('正在测试连接，请稍候完成后再关闭设置。')
            return
        super().done(code)

    def _apply_theme(self, theme):
        bg, surface, ink, border = ('#f5f5f7', '#ffffff', '#202126', '#e2e3e8') if theme == 'light' else ('#111113', '#1b1b20', '#f2f2f5', '#303038')
        self.setStyleSheet(f'''
            QDialog, QWidget {{ background: {bg}; color: {ink}; font-family: "Segoe UI", "Microsoft YaHei UI"; font-size: 13px; }}
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {surface}; padding: 7px; border: 1px solid {border}; border-radius: 7px; }}
            QPushButton {{ background: {surface}; padding: 8px 18px; border: 1px solid {border}; border-radius: 7px; }}
            QPushButton:hover {{ border-color: #6c96f5; }}
            QGroupBox {{ border: 1px solid {border}; border-radius: 10px; margin-top: 16px; padding: 16px 12px 12px; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 5px; }}
            QTabWidget::pane {{ border: none; padding-top: 12px; }}
            QTabBar::tab {{ padding: 10px 20px; border-bottom: 2px solid transparent; }}
            QTabBar::tab:selected {{ color: #6c96f5; border-bottom-color: #6c96f5; }}
        ''')

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
        if self.relay_test_thread is not None:
            self.relay_status.setText('正在测试连接，请完成后再保存设置。')
            return
        if self.relay_token.text() or self.relay_id.text().strip() != self.relay_saved_id:
            self.relay_status.setText('凭据尚未保存，请先点击“保存凭据”，或还原输入。')
            return
        command = self.codex_command.text().strip()
        url = self.balance_url.text().strip()
        if self.enabled['codex'].isChecked() and self.mode.currentData() == 'custom_command' and not command:
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
        ui.update(title=self.title_edit.text().strip() or 'Coding Energy', theme=self.theme.currentData(),
                  width=self.width_input.value(), expanded_height=self.height_input.value(),
                  opacity=self.opacity.value(), always_on_top=self.top.isChecked(),
                  collapsible=self.collapse.isChecked(), show_reset_times=self.reset.isChecked(),
                  compact_summary_show_reset=self.compact_reset.isChecked(),
                  visible_providers=[key for key, check in self.visible.items() if check.isChecked()],
                  taskbar_providers=[key for key, check in self.taskbar_visible.items() if check.isChecked()])
        self.config['app']['refresh_interval_seconds'] = self.interval.value()
        self.config['provider']['timeout_seconds'] = self.timeout.value()
        for key, check in self.enabled.items():
            self.config[key]['enabled'] = check.isChecked()
        self.config['codex'].update(mode=self.mode.currentData(), custom_command=command)
        self.config['kimi']['command'] = self.kimi_command.text().strip()
        self.config['deepseek'].update(balance_url=url, preferred_currency=self.currency.currentText().strip().upper())
        self.config['aicodemirror']['browser_timeout_seconds'] = self.mirror_timeout.value()
        self.config['relayrouter'].update(refresh_interval_seconds=self.relay_interval.value(), use_system_proxy=self.relay_proxy.isChecked())
        try:
            save_config(self.root, self.config)
        except OSError as exc:
            QMessageBox.warning(self, '保存失败', sanitize_message(exc))
            return
        self.accept()
