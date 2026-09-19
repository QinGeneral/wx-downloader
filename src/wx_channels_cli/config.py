from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class AppError(Exception):
    """可直接向用户展示的错误。"""


def app_home() -> Path:
    return Path(os.environ.get("WX_CHANNELS_HOME", "~/.config/wx-channels")).expanduser().resolve()


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise AppError(f"JSON 文件无效：{path}") from exc


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".wx-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def defaults() -> dict:
    return {
        "download_dir": str(Path.home() / "Downloads" / "wx-channels"),
        "cache_dir": str(
            Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser() / "wx-channels"
        ),
        "timeout": 60,
        "retries": 2,
        "quality": "h264",
        "browser": "auto",
    }


def validate_setting(key: str, value):
    if key not in defaults():
        raise AppError(f"未知配置项：{key}")
    if key.endswith("_dir"):
        if not isinstance(value, str) or not value.strip():
            raise AppError(f"{key} 必须是非空路径")
        return str(Path(value).expanduser().resolve())
    if key in ("timeout", "retries"):
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise AppError(f"{key} 必须是整数") from exc
        if isinstance(value, bool) or str(number) != str(value) or not 0 <= number <= 3600:
            raise AppError(f"{key} 必须是 0 到 3600 的整数")
        if key == "timeout" and number == 0:
            raise AppError("timeout 必须大于 0")
        if key == "retries" and number > 10:
            raise AppError("retries 最大为 10")
        return number
    options = {"quality": ("h264", "h265"), "browser": ("auto", "chrome", "chromium", "msedge")}
    if value not in options[key]:
        raise AppError(f"{key} 可选值：{', '.join(options[key])}")
    return value


def load_config() -> dict:
    saved = read_json(app_home() / "config.json", {})
    if not isinstance(saved, dict):
        raise AppError("config.json 必须是 JSON 对象")
    return defaults() | {key: validate_setting(key, value) for key, value in saved.items()}
