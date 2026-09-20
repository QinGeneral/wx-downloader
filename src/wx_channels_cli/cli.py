from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .auth import load_auth, login
from .client import YuanbaoClient
from .config import AppError, app_home, load_config, validate_setting, write_json
from .download import download_one
from .inputs import parse_inputs


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="wx-downloader", description="元宝登录 · 微信视频号下载")
    root.add_argument("--version", action="version", version=__version__)
    subs = root.add_subparsers(dest="command", required=True)
    auth = subs.add_parser("login", help="打开元宝浏览器登录并保存凭据")
    auth.add_argument("--browser", choices=("auto", "chrome", "chromium", "msedge"))
    auth.add_argument("--timeout", type=int, default=300, help="扫码等待秒数，默认 300")
    subs.add_parser("logout", help="删除本地保存的登录凭据")
    subs.add_parser("status", help="查看本地凭据与目录状态，不输出 token")
    config = subs.add_parser("config", help="查看和修改配置").add_subparsers(
        dest="action", required=True
    )
    config.add_parser("show", help="查看配置")
    setter = config.add_parser("set", help="设置配置项")
    setter.add_argument("key")
    setter.add_argument("value")
    down = subs.add_parser("download", help="下载分享链接、JSON 列表或 JSON 文件")
    down.add_argument("sources", nargs="*", help="链接、内联 JSON 或 JSON 文件路径；- 读取标准输入")
    down.add_argument("--input", "-i", action="append", default=[], metavar="JSON_FILE")
    down.add_argument("--output", "-o", help="本次下载成品目录")
    down.add_argument("--cache-dir", help="本次下载临时缓存目录")
    down.add_argument("--quality", choices=("h264", "h265"))
    down.add_argument("--no-login", action="store_true", help="未登录时直接失败，不打开浏览器")
    down.add_argument(
        "--json", action="store_true", help="stdout 仅输出 JSON 结果，日志发往 stderr"
    )
    return root


def collect_sources(args) -> list[str]:
    entries = []
    stdin_used = False

    def read_source(value: str, required_file=False):
        nonlocal stdin_used
        if value == "-":
            if stdin_used:
                raise AppError("标准输入只能读取一次")
            stdin_used = True
            return sys.stdin.read()
        if not required_file and (
            value.startswith("https://") or value.lstrip().startswith(("[", "{", '"'))
        ):
            return value
        file = Path(value).expanduser()
        if required_file or file.is_file():
            try:
                return file.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError) as exc:
                raise AppError(f"无法读取输入文件：{file}") from exc
        return value

    for value in args.sources:
        entries.extend(parse_inputs(read_source(value)))
    for file in args.input:
        entries.extend(parse_inputs(read_source(file, True)))
    if not args.sources and not args.input:
        if sys.stdin.isatty():
            print("请输入视频分享链接或 JSON 列表：", file=sys.stderr)
            entries.extend(parse_inputs(input()))
        else:
            entries.extend(parse_inputs(sys.stdin.read()))
    return list(dict.fromkeys(entries))


def run(args) -> int:
    config = load_config()
    emit = lambda message: print(message, file=sys.stderr)
    if args.command == "config":
        if args.action == "set":
            config[args.key] = validate_setting(args.key, args.value)
            write_json(app_home() / "config.json", config)
        print(json.dumps(config, ensure_ascii=False, indent=2))
    elif args.command == "login":
        if args.timeout <= 0:
            raise AppError("等待登录超时必须大于 0")
        login(args.browser or config["browser"], args.timeout, emit)
    elif args.command == "logout":
        (app_home() / "auth.json").unlink(missing_ok=True)
        print("本地元宝登录凭据已删除。")
    elif args.command == "status":
        try:
            auth = load_auth()
            status = "已保存（服务端有效性将在下载时检查）"
            saved = auth.get("saved_at")
        except AppError:
            status, saved = "未登录或本地 Cookie 已过期", None
        print(
            json.dumps(
                {"auth": status, "saved_at": saved, "config_dir": str(app_home()), **config},
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "download":
        sources = collect_sources(args)  # Validate all input before launching login/network calls.
        for key, value in (
            ("download_dir", args.output),
            ("cache_dir", args.cache_dir),
            ("quality", args.quality),
        ):
            if value is not None:
                config[key] = validate_setting(key, value)
        try:
            auth = load_auth()
        except AppError:
            if args.no_login:
                raise
            login(config["browser"], emit=emit)
            auth = load_auth()
        results = []
        with YuanbaoClient(auth, config["timeout"]) as client:
            for index, source in enumerate(sources, 1):
                emit(f"[{index}/{len(sources)}] {source}")

                def progress(size, total):
                    percent = f" / {total / 1048576:.1f} MiB ({size / total:.0%})" if total else ""
                    emit(f"  已下载 {size / 1048576:.1f} MiB{percent}")

                try:
                    result = download_one(source, client, config, progress)
                    emit(
                        f"  {'跳过已下载' if result['status'] == 'skipped' else '已保存'}：{result['path']}"
                    )
                except (AppError, OSError) as exc:
                    result = {"status": "failed", "source_url": source, "error": str(exc)}
                    emit(f"  失败：{exc}")
                results.append(result)
        counts = {
            kind: sum(r["status"] == kind for r in results)
            for kind in ("downloaded", "skipped", "failed")
        }
        if args.json:
            print(json.dumps({"summary": counts, "results": results}, ensure_ascii=False, indent=2))
        else:
            print(
                f"完成：下载 {counts['downloaded']}，跳过 {counts['skipped']}，失败 {counts['failed']}"
            )
        return 1 if counts["failed"] else 0
    return 0


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        return 130
    except (AppError, OSError, EOFError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
