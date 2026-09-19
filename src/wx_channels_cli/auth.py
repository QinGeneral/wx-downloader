from __future__ import annotations

import time
from urllib.parse import urlsplit

from .client import ORIGIN
from .config import AppError, app_home, read_json, write_json


def cookie_header(cookies: list[dict]) -> str:
    now = time.time()
    valid = []
    for cookie in cookies:
        domain = cookie.get("domain", "").lstrip(".")
        expiry = cookie.get("expires", -1)
        if (
            domain
            and ("yuanbao.tencent.com" == domain or "yuanbao.tencent.com".endswith("." + domain))
            and (expiry == -1 or expiry > now)
            and cookie.get("value")
            and "/api/weixin/get_parse_result".startswith(cookie.get("path", "/"))
        ):
            valid.append(cookie)
    valid.sort(key=lambda c: len(c.get("path", "/")), reverse=True)
    return "; ".join(f"{c['name']}={c['value']}" for c in valid)


def load_auth() -> dict:
    auth = read_json(app_home() / "auth.json", {})
    if not isinstance(auth, dict):
        raise AppError("登录凭据文件格式错误，请运行 wx-downloder login")
    cookie = cookie_header(auth.get("cookies", []))
    names = {part.split("=", 1)[0] for part in cookie.split("; ")}
    if not cookie or not {"hy_user", "hy_token"}.issubset(names):
        raise AppError("没有可用的元宝登录凭据，请先运行 wx-downloder login")
    return auth | {"cookie": cookie}


def login(browser_name: str = "auto", timeout: int = 300, emit=print) -> None:
    from playwright.sync_api import Error as BrowserError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = None
        choices = ("chrome", "chromium") if browser_name == "auto" else (browser_name,)
        for choice in choices:
            try:
                browser = pw.chromium.launch(
                    headless=False, **({"channel": choice} if choice != "chromium" else {})
                )
                break
            except BrowserError:
                continue
        if browser is None:
            raise AppError(
                "无法启动浏览器。请安装 Chrome，或运行 python -m playwright install chromium"
            )
        context = None
        capture = None
        try:
            # Always authenticate afresh: reusing locally unexpired cookies here can
            # immediately re-save a session that the server has already revoked.
            context = browser.new_context(locale="zh-CN")
            page = context.new_page()
            captured = {}

            def capture(request):
                if (
                    urlsplit(request.url).netloc != "yuanbao.tencent.com"
                    or "/api/" not in request.url
                ):
                    return
                # This property reads the event's cached headers without issuing a
                # browser RPC. all_headers() can outlive the page during shutdown.
                for key, value in request.headers.items():
                    if key in (
                        "authorization",
                        "t-userid",
                        "x-id",
                        "x-device-id",
                        "x-hy92",
                        "x-hy93",
                    ):
                        captured[key] = value

            context.on("request", capture)
            page.goto(ORIGIN, wait_until="domcontentloaded", timeout=60000)
            emit("已打开元宝，请在浏览器中完成扫码或手机号登录；检测到登录凭据后自动保存。")
            # Site labels vary; failure to auto-open is harmless, user can click 登录.
            for label in ("登录", "立即登录", "登录 / 注册", "Log In", "Not logged in"):
                try:
                    button = page.get_by_text(label, exact=True).first
                    if button.is_visible():
                        button.click(timeout=1500)
                        break
                except BrowserError:
                    pass
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if page.is_closed():
                    raise AppError("浏览器已关闭，未保存新的登录凭据")
                cookies = context.cookies(ORIGIN + "/api/weixin/get_parse_result")
                names = {
                    c["name"].lower(): c["value"]
                    for c in cookies
                    if c.get("value") and (c.get("expires", -1) == -1 or c["expires"] > time.time())
                }
                # Yuanbao creates anonymous tracking cookies before login; those do not count.
                if names.get("hy_user") and names.get("hy_token"):
                    state = context.storage_state()
                    write_json(
                        app_home() / "auth.json",
                        {
                            "cookies": cookies,
                            "storage_state": state,
                            "headers": captured,
                            "user_agent": page.evaluate("navigator.userAgent"),
                            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                        },
                    )
                    emit("元宝登录凭据已保存（仅当前用户可读写）。")
                    return
                page.wait_for_timeout(1000)
            raise AppError("等待登录超时，未检测到 hy_user/hy_token，请重新运行 wx-downloder login")
        except BrowserError as exc:
            raise AppError("元宝浏览器登录失败，请检查网络后重试") from exc
        finally:
            if context is not None and capture is not None:
                context.remove_listener("request", capture)
            browser.close()
