import json
import sys
from types import SimpleNamespace
from typing import ClassVar

import pytest

from wx_channels_cli.auth import login
from wx_channels_cli.config import AppError, write_json


@pytest.mark.parametrize("mode", ["success", "closed", "timeout"])
def test_browser_login_lifecycle(mode, tmp_path, monkeypatch):
    monkeypatch.setenv("WX_CHANNELS_HOME", str(tmp_path))
    saved = tmp_path / "auth.json"
    write_json(saved, {"old_session": True})
    attempts, closes, waits = [], [], []
    listeners = {}

    class Request:
        url = "https://yuanbao.tencent.com/api/getuserinfo"
        headers: ClassVar[dict[str, str]] = {
            "x-id": "test-user",
            "cookie": "must-not-capture",
            "unrelated": "ignored",
        }

        def all_headers(self):
            pytest.fail("Request callbacks must not make a browser RPC during shutdown")

    def add_listener(event, callback):
        listeners[event] = callback

    def remove_listener(event, callback):
        assert listeners.pop(event) is callback

    cookies = [
        {"name": "hy_user", "value": "user", "domain": ".tencent.com", "expires": -1},
        {"name": "hy_token", "value": "token", "domain": ".tencent.com", "expires": -1},
    ]
    clock = iter([0, 1, 100])
    monkeypatch.setattr("wx_channels_cli.auth.time.monotonic", lambda: next(clock))

    class Page:
        def goto(self, url, **kwargs):
            assert url == "https://yuanbao.tencent.com"
            listeners["request"](Request())
            listeners["request"](SimpleNamespace(url="https://example.com/api/getuserinfo"))

        def get_by_text(self, *_args, **_kwargs):
            return SimpleNamespace(first=SimpleNamespace(is_visible=lambda: False))

        def is_closed(self):
            return mode == "closed"

        def evaluate(self, expression):
            assert expression == "navigator.userAgent"
            return "test-browser"

        def wait_for_timeout(self, duration):
            waits.append(duration)

    class Browser:
        def new_context(self, **kwargs):
            assert "storage_state" not in kwargs  # Revoked credentials must never be reused.
            return SimpleNamespace(
                new_page=Page,
                on=add_listener,
                remove_listener=remove_listener,
                cookies=lambda _: cookies if mode == "success" else [],
                storage_state=lambda: {"cookies": cookies, "origins": []},
            )

        def close(self):
            assert not listeners, "Detach the request callback before closing the browser"
            closes.append(True)

    class Playwright:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(launch=self.launch))

        def __exit__(self, *_):
            pass

        def launch(self, **kwargs):
            attempts.append(kwargs)
            return Browser()

    fake = SimpleNamespace(Error=RuntimeError, sync_playwright=Playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake)
    if mode == "success":
        login(timeout=30, emit=lambda _: None)
        assert json.loads(saved.read_text())["cookies"] == cookies
        assert json.loads(saved.read_text())["headers"] == {"x-id": "test-user"}
    else:
        with pytest.raises(AppError):
            login(timeout=30, emit=lambda _: None)
        assert json.loads(saved.read_text()) == {"old_session": True}
    assert closes == [True]
    assert attempts == [{"headless": False, "channel": "chrome"}]


def test_missing_browser_guidance(tmp_path, monkeypatch):
    monkeypatch.setenv("WX_CHANNELS_HOME", str(tmp_path))

    def launch(**_):
        raise RuntimeError("not installed")

    class Playwright:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(launch=launch))

        def __exit__(self, *_):
            pass

    monkeypatch.setitem(
        sys.modules,
        "playwright.sync_api",
        SimpleNamespace(Error=RuntimeError, sync_playwright=Playwright),
    )
    with pytest.raises(AppError, match="playwright install chromium"):
        login()
