"""Opt-in regression using Chrome with locally mocked Yuanbao responses."""

import json
import os
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from wx_channels_cli.auth import login


@pytest.mark.skipif(
    os.environ.get("WX_DOWNLOADER_BROWSER_TEST") != "1",
    reason="Set WX_DOWNLOADER_BROWSER_TEST=1 to run the Chrome regression",
)
def test_login_closes_cleanly_with_active_requests(tmp_path, monkeypatch, capsys):
    from playwright import sync_api

    monkeypatch.setenv("WX_CHANNELS_HOME", str(tmp_path))
    real_playwright = sync_api.sync_playwright
    requests = []

    def forbidden_rpc(_):
        pytest.fail("all_headers() must never be called from the request listener")

    monkeypatch.setattr(sync_api.Request, "all_headers", forbidden_rpc)

    @contextmanager
    def local_browser():
        with real_playwright() as pw:

            def launch(**kwargs):
                browser = pw.chromium.launch(**(kwargs | {"headless": True}))
                new_context = browser.new_context

                def context_factory(**options):
                    context = new_context(**options)
                    context.set_extra_http_headers({"x-id": "browser-regression"})
                    context.add_cookies(
                        [
                            {
                                "name": "hy_user",
                                "value": "test-user",
                                "url": "https://yuanbao.tencent.com",
                            },
                            {
                                "name": "hy_token",
                                "value": "test-token",
                                "url": "https://yuanbao.tencent.com",
                            },
                        ]
                    )

                    def route(request_route):
                        if "/api/" in request_route.request.url:
                            requests.append(request_route.request.url)
                            request_route.fulfill(json={"ok": True})
                        else:
                            request_route.fulfill(
                                content_type="text/html",
                                body="""<html><script>
                                for (let i = 0; i < 40; i++) fetch('/api/pending?i=' + i);
                                setInterval(() => fetch('/api/pending'), 5);
                                </script></html>""",
                            )

                    context.route("**/*", route)
                    return context

                browser.new_context = context_factory
                return browser

            yield SimpleNamespace(chromium=SimpleNamespace(launch=launch))

    monkeypatch.setattr(sync_api, "sync_playwright", local_browser)
    login(browser_name="chrome", timeout=10)
    saved = json.loads((tmp_path / "auth.json").read_text())
    assert saved["headers"]["x-id"] == "browser-regression"
    assert requests
    output = capsys.readouterr()
    assert "凭据已保存" in output.out
    assert "Exception in callback" not in output.err
    assert "TargetClosedError" not in output.err
