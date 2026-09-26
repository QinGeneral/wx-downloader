---
name: wx-downloader
description: 使用 wx-downloader Python CLI 登录元宝、下载微信视频号分享链接或 JSON 批量清单，并查看状态与配置。适用于用户要求 AI 操作此 CLI 的任务。
---

# wx-downloader CLI

本 Skill 对应独立 Python 命令 `wx-downloader`。先用 `wx-downloader --version` 和 `wx-downloader <子命令> --help` 确认命令可用；源码仓库中可改用 `uv run wx-downloader`。Skill 本身不安装 CLI。支持 Python 3.10+，可通过 `uv tool install wx-downloader` 安装。

## 登录与状态

`wx-downloader status` 只显示本地凭据和目录状态，不能证明服务端会接受该凭据。首次登录或服务端凭据过期时运行 `wx-downloader login`，让用户在打开的元宝浏览器中扫码或完成手机号验证；可用 `--browser chrome|chromium|msedge|auto` 和 `--timeout` 设置登录等待秒数。不要读取、输出或提交 `auth.json` 中的 Cookie 和请求头。`wx-downloader logout` 会删除本地凭据，只在用户要求退出登录时使用。

## 下载

仅接受 `https://weixin.qq.com/sph/...` 格式的普通视频号分享链接。给 URL 加引号，避免 shell 解释其中的特殊字符。单条下载：

```sh
wx-downloader download 'https://weixin.qq.com/sph/VIDEO_ID' --json
```

多个链接可直接作为多个参数传入，或使用 JSON 文件：

```sh
wx-downloader download --input links.json --output ./videos --json
```

`links.json` 可以是字符串数组，或 `{"links":[{"url":"https://weixin.qq.com/sph/VIDEO_ID"}]}`。示例中的 `VIDEO_ID` 须替换为真实分享 ID。还支持对象中的 `share_url`、`shareUrl`、`sourceUrl`、`link`，以及 `urls`、`videos`、`items`、`data` 包装列表。JSON 文件支持 UTF-8 和 UTF-8 BOM。不要把每行一个链接的文本文件传给 `--input`，该选项读取 JSON。也可从标准输入读取：`wx-downloader download - --no-login --json`。

默认没有本地凭据时，`download` 会打开浏览器等待用户登录。无人值守时加 `--no-login`，让缺失凭据立即报错，再请用户完成登录。`--output`、`--cache-dir`、`--quality h264|h265` 仅覆盖本次任务；默认成品目录为 `~/Downloads/wx-channels`。已有记录且文件大小一致时会跳过，不覆盖已有文件。单项失败后批量任务继续处理。

需要机器可读结果时加 `--json`：标准输出为含 `summary` 和逐项 `results` 的 JSON，进度与错误写入标准错误。检查每项的 `status`、`path` 或 `error`，以及退出码：全部成功或跳过为 0，有失败为 1，用户取消为 130。

## 配置

`wx-downloader config show` 查看当前配置；`wx-downloader config set <key> <value>` 修改持久配置。可设置 `download_dir`、`cache_dir`、`quality`、`timeout`、`retries` 和 `browser`。临时目录与质量优先用下载命令参数，避免无意修改后续任务的默认值。配置和凭据默认位于 `~/.config/wx-channels/`；`WX_CHANNELS_HOME` 可更改配置目录。成品目录中的 `.wx-*.json` 是下载去重记录，应保留。
