from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

import httpx

from .client import USER_AGENT
from .config import AppError, read_json, write_json


def safe_name(value: str) -> str:
    name = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|\s]+', "_", value).strip("._ ")[:60]
    return name or "video"


def stream_video(url: str, cache_dir: Path, timeout: int, progress, transport=None) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="wx-video-", suffix=".part", dir=cache_dir)
    path = Path(name)
    complete = False
    try:
        with (
            os.fdopen(fd, "wb") as output,
            httpx.Client(
                timeout=timeout,
                follow_redirects=True,
                transport=transport,
                headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
            ) as http,
            http.stream("GET", url) as response,
        ):
            if response.status_code != 200:
                raise AppError(f"视频下载返回 HTTP {response.status_code}")
            content_type = response.headers.get("content-type", "").lower()
            if any(kind in content_type for kind in ("text/", "json", "xml", "mpegurl")):
                raise AppError("媒体地址返回网页或错误信息，未保存为视频")
            try:
                total = int(response.headers.get("content-length", "0"))
            except ValueError as exc:
                raise AppError("媒体服务器返回无效的文件长度") from exc
            size, last = 0, 0.0
            head = bytearray()
            for chunk in response.iter_bytes(256 * 1024):
                if len(head) < 32:
                    head.extend(chunk[: 32 - len(head)])
                output.write(chunk)
                size += len(chunk)
                now = time.monotonic()
                if now - last >= 1:
                    progress(size, total)
                    last = now
            if not size or (total and size != total):
                raise AppError(f"视频传输不完整：收到 {size} 字节，预期 {total}")
            if bytes(head[4:8]) not in (b"ftyp", b"moov", b"mdat", b"free", b"wide"):
                raise AppError("下载内容不是有效的 MP4 文件，未保存成品")
            output.flush()
            os.fsync(output.fileno())
            progress(size, total)
        complete = True
        return path
    finally:
        if not complete:
            path.unlink(missing_ok=True)


def publish(temp: Path, target: Path) -> None:
    """Cross-filesystem safe; never replace existing files, clean interrupted copies."""
    created = False
    try:
        with target.open("xb") as out:
            created = True
            with temp.open("rb") as source:
                shutil.copyfileobj(source, out, 1024 * 1024)
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        if created:
            target.unlink(missing_ok=True)
        raise


def download_one(
    source: str, resolver, config: dict, progress=lambda *_: None, transport=None
) -> dict:
    directory = Path(config["download_dir"]).expanduser().resolve()
    cache = Path(config["cache_dir"]).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    identity = hashlib.sha256(source.encode()).hexdigest()[:12]
    receipt = directory / f".wx-{identity}.json"
    previous = read_json(receipt, {})
    if isinstance(previous, dict) and previous.get("source_url") == source:
        filename = previous.get("filename", "")
        if filename and Path(filename).name == filename:
            target = directory / filename
            if target.is_file() and target.stat().st_size == previous.get("bytes", 0) > 0:
                return {
                    "status": "skipped",
                    "source_url": source,
                    "path": str(target),
                    "bytes": target.stat().st_size,
                }
    for attempt in range(config["retries"] + 1):
        temp = None
        try:
            video = resolver.resolve(source, config["quality"])
            filename = f"{safe_name(video['description'])}-{identity}.mp4"
            target = directory / filename
            if target.exists():
                raise AppError(f"目标文件已存在但无匹配下载记录，请移动或重命名后重试：{target}")
            temp = stream_video(video["media_url"], cache, config["timeout"], progress, transport)
            publish(temp, target)
            result = {
                "status": "downloaded",
                "source_url": source,
                "path": str(target),
                "bytes": target.stat().st_size,
                "filename": filename,
                "description": video["description"],
                "author": video["author"],
            }
            try:
                write_json(receipt, result)
            except OSError as exc:
                raise AppError(f"视频已保存到 {target}，但下载记录保存失败") from exc
            return result
        except (httpx.TransportError, AppError) as exc:
            # Retry network/temporary failures, never repeatedly retry login or invalid input.
            retryable = (
                isinstance(exc, httpx.TransportError)
                or "HTTP 5" in str(exc)
                or "HTTP 429" in str(exc)
            )
            if not retryable or attempt == config["retries"]:
                if isinstance(exc, httpx.TransportError):
                    raise AppError("网络请求失败或超时，请检查网络后重试") from exc
                raise
            time.sleep(min(2**attempt, 8))
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
    raise AssertionError("unreachable")
