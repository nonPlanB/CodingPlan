"""Isolated, memory-only browser for user login and read-only wallet requests.

The only persisted browser state is a DPAPI-encrypted first-party cookie jar.
No WebChannel/native bridge is exposed to websites.
"""
from __future__ import annotations

import base64
from datetime import datetime
import json
from pathlib import Path
import sys

from PySide6.QtCore import QDateTime, QTimer, QUrl, Qt
from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from core.aicodemirror_session import SITE, load_session, save_session, session_lock
from providers.aicodemirror_provider import parse_wallet, result


def allowed_cookie(cookie):
    return cookie.domain().lstrip(".").lower() in {"www.aicodemirror.ai", "aicodemirror.ai"} and cookie.isSecure()


def cookie_key(cookie):
    return (bytes(cookie.name()), cookie.domain().lstrip(".").lower(), cookie.path() or "/")


def cookie_signature(cookie):
    return (bytes(cookie.value()), cookie.expirationDate().toSecsSinceEpoch())


def decode_cookies(saved):
    cookies = []
    for encoded in saved.get("cookies", []):
        for cookie in QNetworkCookie.parseCookies(base64.b64decode(encoded, validate=True)):
            if allowed_cookie(cookie) and (cookie.isSessionCookie() or cookie.expirationDate() > QDateTime.currentDateTimeUtc()):
                cookies.append(cookie)
    return cookies


FETCH = """(() => {
    if (location.origin !== 'https://www.aicodemirror.ai') return;
    window.__codingPlanWallet = null;
    (async () => {
        try {
            // Use Auth.js' existing session endpoint. It may rotate/extend a valid
            // cookie; the website alone decides whether renewal is permitted.
            const session = await fetch('/api/auth/session', {
                credentials: 'same-origin', cache: 'no-store', redirect: 'error',
                signal: AbortSignal.timeout(12000)
            });
            let sessionExpires = null;
            if (session.ok && (session.headers.get('content-type') || '').includes('application/json')) {
                const state = await session.json();
                sessionExpires = typeof state?.expires === 'string' ? state.expires : null;
            }
            const r = await fetch('/api/wallet', { credentials: 'same-origin',
                cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(12000) });
            const json = (r.headers.get('content-type') || '').includes('application/json');
            window.__codingPlanWallet = { http: r.status, json,
                payload: r.ok && json ? await r.json() : null, sessionExpires };
        } catch (_) { window.__codingPlanWallet = { networkError: true }; }
    })();
})()"""


class SitePage(QWebEnginePage):
    def __init__(self, profile, owner):
        super().__init__(profile, owner)
        self.owner = owner

    def acceptNavigationRequest(self, url, kind, main):
        if self.owner.initializing and url.scheme() == "data":
            return True
        if not main:
            return url.scheme() in {"https", "about"}
        hosts = {"www.aicodemirror.ai", "aicodemirror.ai"}
        if self.owner.login:
            hosts.update({"github.com", "accounts.google.com"})
        return url.scheme() == "https" and url.host().lower() in hosts and not url.userName() and not url.password()

    def javaScriptConsoleMessage(self, *args):
        pass  # Website console messages can contain private account information.


class WalletBrowser(QWidget):
    def __init__(self, root, mode, timeout):
        super().__init__()
        self.root, self.login = root, mode == "login"
        self.initializing = True
        self.jar, self.original = {}, {}
        self.verified = self.done = self.busy = False
        self.last_result = None
        self.saved = load_session(root)
        cookies = decode_cookies(self.saved)
        self.restored = bool(cookies)
        self.original = {cookie_key(c): cookie_signature(c) for c in cookies}
        self.setWindowTitle("AICodeMirror 官方登录 · CodingPlan")
        self.resize(1080, 800)
        layout = QVBoxLayout(self)
        self.label = QLabel("请在下方官方网站登录；密码不会保存。登录成功后点击“保存并关闭”。")
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.address = QLabel(SITE)
        self.address.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.address)
        # An unnamed profile is off-the-record. Chromium storage/cache is memory-only.
        self.profile = QWebEngineProfile(self)
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        self.profile.downloadRequested.connect(lambda download: download.cancel())
        self.view = QWebEngineView(self)
        self.page = SitePage(self.profile, self)
        self.page.urlChanged.connect(lambda url: self.address.setText(url.scheme() + "://" + url.host() + url.path()))
        self.view.setPage(self.page)
        self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)
        self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False)
        self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        self.page.permissionRequested.connect(lambda permission: permission.deny())
        layout.addWidget(self.view)
        self.finish_button = QPushButton("保存并关闭")
        self.finish_button.setEnabled(False)
        self.finish_button.clicked.connect(lambda: self.finish(self.last_result))
        layout.addWidget(self.finish_button)
        store = self.profile.cookieStore()
        store.cookieAdded.connect(self.cookie_added)
        store.cookieRemoved.connect(self.cookie_removed)
        self.persist_timer = QTimer(self)
        self.persist_timer.setSingleShot(True)
        self.persist_timer.timeout.connect(self.persist)
        self.poll = QTimer(self)
        self.poll.timeout.connect(self.poll_result)
        self.poll.start(250)
        self.retry = QTimer(self)
        self.retry.timeout.connect(self.fetch_wallet)
        if self.login:
            self.retry.start(5000)
        self.page.loadFinished.connect(self.loaded)
        self.timeout_timer = QTimer(self)
        self.timeout_timer.setSingleShot(True)
        self.timeout_timer.timeout.connect(lambda: self.finish(result("offline", "余额查询超时，请检查网络或打开登录窗口。")))
        if not self.login:
            self.timeout_timer.start(int(max(1, timeout) * 1000))
        self.restoring = {cookie_key(c) for c in cookies}
        self.pending_cookies = cookies
        self.started = False
        # Initialize Chromium's network context before using its cookie store.
        # This local, empty document makes no requests to the website.
        self.view.setHtml("<!doctype html><title>准备登录会话</title>", QUrl(SITE))

    def install_cookies(self):
        for cookie in self.pending_cookies:
            restored = QNetworkCookie(cookie)
            # Qt exposes the origin host for host-only cookies. Re-injecting
            # that as Domain breaks __Host- cookies and widens their scope.
            if not restored.domain().startswith("."):
                restored.setDomain("")
            self.profile.cookieStore().setCookie(restored, QUrl(SITE))
        # Cookie injection is asynchronous. Do not navigate until acknowledged.
        QTimer.singleShot(3000 if self.pending_cookies else 0, self.start)

    def cookie_added(self, cookie):
        if not allowed_cookie(cookie):
            return
        key = cookie_key(cookie)
        self.jar[key] = QNetworkCookie(cookie)
        if key in self.restoring:
            self.restoring.discard(key)
            if not self.restoring:
                QTimer.singleShot(0, self.start)
        if self.verified:
            self.persist_timer.start(200)

    def cookie_removed(self, cookie):
        self.jar.pop(cookie_key(cookie), None)
        if self.verified:
            self.persist_timer.start(200)

    def start(self):
        if self.started:
            return
        self.started = True
        if self.restoring:
            self.finish(result("error", "无法恢复完整登录会话，请重新登录。"))
            return
        self.view.setUrl(QUrl(SITE + "/dashboard"))

    def loaded(self, ok):
        if self.initializing:
            self.initializing = False
            self.install_cookies()
            return
        self.busy = False
        if not ok:
            if self.login:
                self.label.setText("网站暂时无法加载。请检查网络或代理设置后重新打开登录窗口。")
            else:
                self.finish(result("offline", "网站无法加载，请检查网络或代理设置。"))
            return
        self.fetch_wallet()

    def fetch_wallet(self):
        url = self.page.url()
        if self.done or self.busy or url.scheme() != "https" or url.host() != "www.aicodemirror.ai":
            return
        self.busy = True
        self.page.runJavaScript(FETCH)

    def poll_result(self):
        if self.busy and not self.done:
            # ApplicationWorld would not share the page's same-origin fetch state.
            self.page.runJavaScript("JSON.stringify(window.__codingPlanWallet || null)", self.received)

    def received(self, value):
        if self.done or not self.busy or not isinstance(value, str):
            return
        try:
            data = json.loads(value)
        except ValueError:
            return
        if not isinstance(data, dict):
            return
        self.busy = False
        if data.get("networkError"):
            reading = result("offline", "无法连接余额服务，请检查网络、代理或网站访问限制。")
        elif not data.get("json"):
            reading = result("error", "网站返回安全验证或非 JSON 页面，请打开登录窗口检查；尚不能判定登录已失效。")
        elif data.get("http") == 401:
            reading = result("unsupported", "网站登录已失效，请在设置中重新登录。", needsLogin=True)
        elif data.get("http") == 403:
            reading = result("error", "网站拒绝访问，请打开登录窗口检查登录状态或安全验证。")
        elif data.get("http") != 200:
            reading = result("error", "余额服务暂时不可用，请稍后重试。")
        else:
            reading = parse_wallet(data.get("payload"))
        if reading["status"] == "ok":
            self.verified = True
            auth_cookies = [c for c in self.jar.values() if b"session-token" in bytes(c.name())]
            reading["sessionInfo"] = {
                "restoredSessionVerified": self.restored,
                "persistentAuthCookies": sum(not c.isSessionCookie() for c in auth_cookies),
                "renewalObserved": any(self.original.get(cookie_key(c)) != cookie_signature(c) for c in auth_cookies) if self.restored else False,
                "verifiedAt": reading["lastSuccessAt"],
            }
            # Session expiry is metadata only; no JWTs or account details leave the helper.
            expiry = data.get("sessionExpires")
            if isinstance(expiry, str):
                try:
                    datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                    reading["sessionInfo"]["expiresAt"] = expiry
                except ValueError:
                    pass
            self.last_result = reading
            if not self.persist():
                return
            if self.login:
                self.label.setText(f"登录成功，按量余额 {reading['balance']['display']}。会话已加密保存，可点击保存并关闭。")
                self.finish_button.setEnabled(True)
            else:
                # Allow Chromium's Set-Cookie notifications to settle before exit.
                QTimer.singleShot(300, lambda: self.finish(reading))
        elif self.login:
            if self.verified:
                self.finish_button.setEnabled(False)
                self.last_result = None
            self.label.setText(reading["message"] + " 请在官方网站完成登录。")
        else:
            self.finish(reading)

    def persist(self):
        if not self.verified:
            return True
        try:
            save_session(self.root, {"version": 1,
                "cookies": [base64.b64encode(bytes(c.toRawForm())).decode("ascii") for c in self.jar.values()],
                "verification": (self.last_result or {}).get("sessionInfo", {})})
            return True
        except (OSError, ValueError):
            self.finish(result("error", "登录成功但无法加密保存会话，请检查数据目录权限。"))
            return False

    def finish(self, reading):
        if self.done:
            return
        self.done = True
        self.poll.stop()
        self.retry.stop()
        self.persist_timer.stop()
        if reading is None:
            reading = result(message="登录窗口已关闭，尚未确认登录。")
        self.last_result = reading
        if sys.stdout is not None:
            print("AICM_RESULT:" + json.dumps(reading, ensure_ascii=True), flush=True)
        QApplication.instance().quit()

    def closeEvent(self, event):
        if self.verified and self.last_result:
            self.persist()
        self.finish(self.last_result)
        event.accept()


def run_browser(root: Path, mode: str, timeout: float):
    try:
        with session_lock(root):
            app = QApplication([])
            window = WalletBrowser(root, mode, timeout)
            if mode == "login":
                window.show()
            app.exec()
            # Destroy page before its profile to avoid Chromium teardown warnings.
            import shiboken6
            shiboken6.delete(window.view)
            shiboken6.delete(window.page)
            shiboken6.delete(window.profile)
            shiboken6.delete(window)
            return 0
    except (OSError, ValueError):
        if sys.stdout is not None:
            print("AICM_RESULT:" + json.dumps(result("error", "无法读取登录会话，或另一个登录/刷新窗口尚未关闭。请稍后重试，必要时清除本地登录。"), ensure_ascii=True), flush=True)
        return 1
