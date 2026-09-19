from __future__ import annotations

import json
import re
from urllib.parse import urlsplit, urlunsplit

from .config import AppError


def normalize_url(value: str) -> str:
    try:
        url = urlsplit(value.strip())
        if (
            url.scheme != "https"
            or url.netloc != "weixin.qq.com"
            or not re.fullmatch(r"/sph/[A-Za-z0-9_-]+/?", url.path)
        ):
            raise ValueError
    except ValueError as exc:
        raise AppError("请输入 https://weixin.qq.com/sph/... 格式的视频号分享链接") from exc
    return urlunsplit((url.scheme, url.netloc, url.path.rstrip("/"), "", ""))


def parse_inputs(raw: str) -> list[str]:
    """链接、字符串数组、对象数组，以及 links/urls/videos/items/data 包装对象。"""
    raw = raw.strip()
    if not raw:
        raise AppError("输入为空")
    try:
        value = json.loads(raw) if raw[0] in '[{"' else raw
    except ValueError as exc:
        raise AppError("输入 JSON 格式无效") from exc

    def walk(item):
        if isinstance(item, str):
            yield normalize_url(item)
        elif isinstance(item, list):
            for child in item:
                yield from walk(child)
        elif isinstance(item, dict):
            for key in ("url", "share_url", "shareUrl", "sourceUrl", "link"):
                if key in item:
                    yield from walk(item[key])
                    return
            for key in ("links", "urls", "videos", "items", "data"):
                if key in item:
                    yield from walk(item[key])
                    return
            raise AppError("JSON 对象需要 url/share_url 字段或 links/urls/videos/items/data 列表")
        else:
            raise AppError("JSON 中的链接必须是字符串或带 url 字段的对象")

    result = list(dict.fromkeys(walk(value)))
    if not result:
        raise AppError("输入列表中没有视频链接")
    return result
