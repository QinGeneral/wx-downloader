from __future__ import annotations

import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from .config import AppError
from .inputs import normalize_url

ORIGIN = "https://yuanbao.tencent.com"
PARSE_URL = ORIGIN + "/api/weixin/get_parse_result"
PREVIEW = "https://channels.weixin.qq.com/finder-preview"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"


def object_field(data: dict, key: str) -> dict:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def http_url(value: str):
    try:
        url = urlsplit(value)
        if url.scheme not in ("http", "https") or not url.netloc or url.username:
            raise ValueError
        return url
    except ValueError as exc:
        raise AppError("接口返回无效的视频地址") from exc


def json_response(response: httpx.Response, stage: str) -> dict:
    if not 200 <= response.status_code < 300:
        hint = "，请运行 wx-downloder login 重新登录" if response.status_code in (401, 403) else ""
        raise AppError(f"{stage}返回 HTTP {response.status_code}{hint}")
    try:
        data = response.json()
    except ValueError as exc:
        raise AppError(f"{stage}返回非 JSON 数据") from exc
    if not isinstance(data, dict):
        raise AppError(f"{stage}返回格式异常")
    return data


class YuanbaoClient:
    def __init__(self, auth: dict, timeout: int = 60, transport=None):
        self.auth = auth
        # Cookies are attached ONLY to the Yuanbao POST, never as client defaults.
        self.http = httpx.Client(timeout=timeout, transport=transport, follow_redirects=False)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.http.close()

    def resolve(self, source: str, quality: str = "h264") -> dict:
        source = normalize_url(source)
        headers = {
            "User-Agent": self.auth.get("user_agent") or USER_AGENT,
            "Origin": ORIGIN,
            "Referer": ORIGIN + "/",
            "Accept": "application/json",
            "x-source": "web",
            "Cookie": self.auth["cookie"],
        }
        for key, value in self.auth.get("headers", {}).items():
            if key in ("authorization", "t-userid", "x-id", "x-device-id", "x-hy92", "x-hy93"):
                headers[key] = value
        result = json_response(
            self.http.post(
                PARSE_URL,
                headers=headers,
                json={
                    "type": "video_channel_url",
                    "url": source,
                    "scene": 1,
                },
            ),
            "元宝解析接口",
        )
        if result.get("code") != 0:
            raise AppError(f"元宝解析失败（code={result.get('code')}），请重新登录并检查链接")
        parsed = result.get("data")
        if not isinstance(parsed, dict) or not isinstance(parsed.get("playable_url"), str):
            raise AppError("元宝未返回视频预览地址")
        url = http_url(parsed["playable_url"])
        query = parse_qs(url.query)
        if (
            url.scheme != "https"
            or url.netloc != "channels.weixin.qq.com"
            or not all(query.get(k) for k in ("token", "eid"))
        ):
            raise AppError("元宝未返回有效的预览 token/eid")
        params = {
            "_rid": f"{int(time.time()):x}-{secrets.token_hex(4)}",
            "_pageUrl": PREVIEW + "/pages/feed",
        }
        profile = json_response(
            self.http.post(
                PREVIEW + "/api/feed/get_feed_info?" + urlencode(params),
                headers={
                    "User-Agent": headers["User-Agent"],
                    "Origin": "https://channels.weixin.qq.com",
                    "Referer": parsed["playable_url"],
                },
                json={"baseReq": {"generalToken": query["token"][0]}, "exportId": query["eid"][0]},
            ),
            "视频号预览接口",
        )
        data = profile.get("data")
        error = object_field(data, "errMsg") if isinstance(data, dict) else {}
        if (
            profile.get("errCode", 0) != 0
            or not isinstance(data, dict)
            or any(error.get(k) for k in ("type", "title", "content"))
        ):
            raise AppError("视频号预览失败，视频可能已删除、不可见或预览凭证失效")
        feed = data.get("feedInfo")
        if not isinstance(feed, dict) or feed.get("mediaType") != 4:
            raise AppError("链接不是可下载的普通视频，暂不支持图集或直播")
        candidates = [quality, "h265" if quality == "h264" else "h264"]
        media = object_field(feed, candidates[0] + "VideoInfo").get("videoUrl")
        media = (
            media
            or feed.get("videoUrl")
            or object_field(feed, candidates[1] + "VideoInfo").get("videoUrl")
        )
        if not isinstance(media, str):
            raise AppError("视频详情缺少有效的媒体下载地址")
        http_url(media)
        return {
            "source_url": source,
            "media_url": media,
            "description": str(feed.get("description") or parsed.get("desc") or "video"),
            "author": str(
                object_field(data, "authorInfo").get("nickname") or parsed.get("author") or ""
            ),
            "profile": profile,
        }
