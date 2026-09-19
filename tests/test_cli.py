import json
import os
from pathlib import Path

import httpx
import pytest

from wx_channels_cli import cli
from wx_channels_cli.auth import cookie_header, load_auth
from wx_channels_cli.client import YuanbaoClient
from wx_channels_cli.config import AppError, defaults, write_json
from wx_channels_cli.download import download_one, publish, stream_video
from wx_channels_cli.inputs import parse_inputs

SOURCE = "https://weixin.qq.com/sph/abc"
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 128


def test_public_command_name():
    assert cli.parser().prog == "wx-downloder"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("WX_CHANNELS_HOME", str(tmp_path / "settings"))


@pytest.fixture
def config(tmp_path):
    return defaults() | {
        "download_dir": str(tmp_path / "videos"),
        "cache_dir": str(tmp_path / "cache"),
        "retries": 0,
    }


def mock_service(parse=None, preview=None, media=None):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.host == "yuanbao.tencent.com":
            assert request.headers["cookie"] == "hy_user=me; hy_token=secret"
            assert json.loads(request.content) == {
                "type": "video_channel_url",
                "url": SOURCE,
                "scene": 1,
            }
            return httpx.Response(
                200,
                json=parse
                if parse is not None
                else {
                    "code": 0,
                    "data": {
                        "playable_url": "https://channels.weixin.qq.com/finder-preview/pages/feed?token=preview&eid=eid"
                    },
                },
            )
        assert "cookie" not in request.headers
        assert "authorization" not in request.headers
        if request.url.host == "channels.weixin.qq.com":
            assert json.loads(request.content) == {
                "baseReq": {"generalToken": "preview"},
                "exportId": "eid",
            }
            return httpx.Response(
                200,
                json=preview
                if preview is not None
                else {
                    "errCode": 0,
                    "data": {
                        "feedInfo": {
                            "mediaType": 4,
                            "description": "测试/视频",
                            "h264VideoInfo": {"videoUrl": "https://cdn.example/video.mp4"},
                        },
                        "authorInfo": {"nickname": "作者"},
                    },
                },
            )
        assert request.url.host == "cdn.example"
        return media or httpx.Response(200, content=MP4, headers={"content-type": "video/mp4"})

    return httpx.MockTransport(handler), seen


def resolver(transport):
    return YuanbaoClient(
        {"cookie": "hy_user=me; hy_token=secret", "headers": {"authorization": "Bearer secret"}},
        transport=transport,
    )


@pytest.mark.parametrize(
    "raw",
    [
        SOURCE + "?from=share#x",
        json.dumps([SOURCE, SOURCE + "?x=1"]),
        json.dumps({"links": [{"url": SOURCE, "title": "备注"}]}),
        json.dumps({"data": {"videos": [{"shareUrl": SOURCE}]}}),
    ],
)
def test_inputs(raw):
    assert parse_inputs(raw) == [SOURCE]


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "[]",
        "{}",
        "[123]",
        "[",
        "https://example.com/sph/abc",
        "https://weixin.qq.com@evil.com/sph/abc",
        "https://weixin.qq.com/not-sph/abc",
    ],
)
def test_invalid_inputs(raw):
    with pytest.raises(AppError):
        parse_inputs(raw)


def test_full_flow_and_skip(config):
    transport, seen = mock_service()
    with resolver(transport) as client:
        first = download_one(SOURCE, client, config, transport=transport)
        assert first["status"] == "downloaded"
        assert Path(first["path"]).read_bytes() == MP4
        assert "测试_视频" in first["path"]
        assert download_one(SOURCE, client, config, transport=transport)["status"] == "skipped"
    assert len(seen) == 3
    assert not list(Path(config["cache_dir"]).iterdir())
    assert "secret" not in next(Path(config["download_dir"]).glob(".wx-*.json")).read_text()


@pytest.mark.parametrize(
    "parse,preview",
    [
        ({"code": 401}, None),
        ({"code": 0, "data": {}}, None),
        ({"code": 0, "data": {"playable_url": "https://evil.test/?token=a&eid=b"}}, None),
        (None, {"errCode": 403}),
        (None, {"errCode": 0, "data": {"errMsg": {"title": "已删除"}}}),
        (None, {"data": {"feedInfo": {"mediaType": 2}}}),
        (None, {"data": {"feedInfo": {"mediaType": 4}}}),
    ],
)
def test_api_failures(config, parse, preview):
    transport, _ = mock_service(parse, preview)
    with resolver(transport) as client, pytest.raises(AppError):
        download_one(SOURCE, client, config, transport=transport)
    assert not list(Path(config["download_dir"]).iterdir())


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(403, content=b"denied"),
        httpx.Response(200, content=b""),
        httpx.Response(200, content=b"<!doctype html>", headers={"content-type": "text/html"}),
        httpx.Response(
            200, content=b"not video", headers={"content-type": "application/octet-stream"}
        ),
        httpx.Response(200, content=MP4, headers={"content-length": "999"}),
    ],
)
def test_bad_download_leaves_no_files(config, response):
    transport, _ = mock_service(media=response)
    with resolver(transport) as client, pytest.raises(AppError):
        download_one(SOURCE, client, config, transport=transport)
    assert not list(Path(config["download_dir"]).iterdir())
    assert not list(Path(config["cache_dir"]).iterdir())


def test_publish_never_overwrites(tmp_path):
    source, target = tmp_path / "part", tmp_path / "video.mp4"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    with pytest.raises(FileExistsError):
        publish(source, target)
    assert target.read_bytes() == b"old"


def test_cancellation_removes_partial(config):
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=MP4))

    def cancel(*_):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        stream_video(
            "https://cdn.example/video.mp4", Path(config["cache_dir"]), 10, cancel, transport
        )
    assert not list(Path(config["cache_dir"]).iterdir())


def test_auth_domain_and_expiration(tmp_path):
    cookies = [
        {"name": "hy_user", "value": "user", "domain": ".tencent.com", "expires": -1},
        {"name": "hy_token", "value": "token", "domain": "yuanbao.tencent.com", "expires": -1},
        {"name": "expired", "value": "no", "domain": ".tencent.com", "expires": 1},
        {"name": "unrelated", "value": "no", "domain": ".qq.com", "expires": -1},
        {
            "name": "wrongpath",
            "value": "no",
            "domain": ".tencent.com",
            "path": "/login",
            "expires": -1,
        },
    ]
    assert cookie_header(cookies) == "hy_user=user; hy_token=token"
    path = tmp_path / "settings" / "auth.json"
    write_json(path, {"cookies": cookies})
    assert load_auth()["cookie"] == "hy_user=user; hy_token=token"
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


def test_cli_config_status_logout(tmp_path, capsys):
    assert cli.main(["config", "set", "cache_dir", str(tmp_path / "my cache")]) == 0
    assert json.loads(capsys.readouterr().out)["cache_dir"] == str(tmp_path / "my cache")
    assert cli.main(["config", "set", "timeout", "0"]) == 1
    assert "timeout" in capsys.readouterr().err
    write_json(
        tmp_path / "settings" / "auth.json",
        {"cookies": [{"name": "hy_token", "value": "secret", "domain": ".tencent.com"}]},
    )
    assert cli.main(["status"]) == 0
    assert "secret" not in capsys.readouterr().out
    assert cli.main(["logout"]) == 0
    assert not (tmp_path / "settings" / "auth.json").exists()


def test_batch_continues_after_failure(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_auth", lambda: {"cookie": "test"})
    calls = []

    def download(source, *_):
        calls.append(source)
        if len(calls) == 1:
            raise AppError("模拟不可见视频")
        return {"status": "downloaded", "path": "video.mp4", "source_url": source}

    monkeypatch.setattr(cli, "download_one", download)
    file = tmp_path / "links.json"
    file.write_text(
        json.dumps([SOURCE, "https://weixin.qq.com/sph/def", SOURCE]), encoding="utf-8-sig"
    )
    assert cli.main(["download", "--input", str(file), "--no-login", "--json"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["summary"] == {"downloaded": 1, "skipped": 0, "failed": 1}
    assert len(calls) == 2


def test_invalid_batch_does_not_launch_login(monkeypatch):
    monkeypatch.setattr(cli, "login", lambda *_: pytest.fail("should not open browser"))
    assert cli.main(["download", json.dumps([SOURCE, "invalid"])]) == 1


def test_missing_auth_no_login():
    assert cli.main(["download", SOURCE, "--no-login"]) == 1


def test_no_credentials_in_redirect():
    transport = httpx.MockTransport(
        lambda _: httpx.Response(302, headers={"location": "https://evil.test/"})
    )
    with resolver(transport) as client, pytest.raises(AppError, match="HTTP 302"):
        client.resolve(SOURCE)


def test_network_retry(config, monkeypatch):
    config["retries"] = 1
    monkeypatch.setattr("wx_channels_cli.download.time.sleep", lambda _: None)
    base, seen = mock_service()
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        if count == 1:
            raise httpx.ConnectError("failed")
        return base.handle_request(request)

    transport = httpx.MockTransport(handler)
    with resolver(transport) as client:
        assert download_one(SOURCE, client, config, transport=transport)["status"] == "downloaded"
    assert count == 4
    assert len(seen) == 3
