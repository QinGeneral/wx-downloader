# wx-downloader

通过腾讯元宝登录解析微信视频号分享链接，将视频下载为 MP4。支持单链接、JSON 批量下载、下载去重，以及独立配置成品目录和临时缓存目录。

当前版本：**[0.1.2 · PyPI](https://pypi.org/project/wx-downloader/0.1.2/)**。包名和 CLI 命令统一为 `wx-downloader`。

[GitHub 仓库](https://github.com/QinGeneral/wx-downloader) · [发布工作流](https://github.com/QinGeneral/wx-downloader/actions/workflows/release.yml)

## 安装

需要 Python 3.10+；浏览器登录支持 Chrome、Playwright Chromium 和 Microsoft Edge。默认优先使用 Chrome。

```bash
uv tool install wx-downloader
wx-downloader --version
wx-downloader --help
```

固定安装版本：

```bash
uv tool install wx-downloader==0.1.2
```

也可以在 Python 虚拟环境中使用 `python -m pip install wx-downloader`。

未安装 Chrome 时，可以安装 Chromium 并指定登录浏览器：

```bash
uv tool run --from wx-downloader playwright install chromium
wx-downloader config set browser chromium
```

如果终端提示找不到 `wx-downloader`，运行 `uv tool update-shell` 后重新打开终端。

## 快速开始

```bash
# 打开元宝，扫码或使用手机号登录；登录成功后自动保存凭据并关闭窗口
wx-downloader login

# 将链接替换为微信分享生成的真实视频号链接
wx-downloader download 'https://weixin.qq.com/sph/实际分享ID'

# 查看保存的登录状态和目录配置
wx-downloader status
```

默认成品目录为 `~/Downloads/wx-channels`。首次下载时若没有可用的本地凭据，会自动打开登录窗口。服务端登录状态过期后，重新运行 `wx-downloader login`。

支持的链接格式是 `https://weixin.qq.com/sph/...`。会自动去除分享参数和重复项；暂不支持公众号文章、直播、图集、微信内部短口令或任意视频直链。

## 批量下载

直接传入多个链接：

```bash
wx-downloader download 'https://weixin.qq.com/sph/ID1' 'https://weixin.qq.com/sph/ID2'
```

将以下内容保存为 `links.json`，并替换其中的示例链接：

```json
{
  "links": [
    "https://weixin.qq.com/sph/ID1",
    {"url": "https://weixin.qq.com/sph/ID2", "title": "可选备注"}
  ]
}
```

```bash
wx-downloader download --input links.json

# 也可以直接传入文件路径或内联 JSON
wx-downloader download links.json
wx-downloader download '["https://weixin.qq.com/sph/ID1", {"url":"https://weixin.qq.com/sph/ID2"}]'

# 从管道读取；缺少凭据时直接失败；stdout 只输出 JSON 结果
cat links.json | wx-downloader download - --no-login --json
```

JSON 支持字符串数组、带 `url` / `share_url` / `shareUrl` / `sourceUrl` / `link` 字段的对象，以及 `links` / `urls` / `videos` / `items` / `data` 包装的列表。`title` 仅作备注，成品文件名使用解析得到的视频标题。文件支持 UTF-8 和 UTF-8 BOM。

`wx-downloader download` 不带参数时，在终端提示输入链接或 JSON；通过管道调用时读取标准输入。程序先验证全部输入，再开始登录和下载。

## 目录与下载配置

```bash
# 配置成品目录和临时缓存目录
wx-downloader config set download_dir '~/Downloads/微信视频'
wx-downloader config set cache_dir '~/Downloads/视频缓存'

# 仅本次任务覆盖目录和视频编码偏好
wx-downloader download --input links.json --output './videos' --cache-dir './cache' --quality h264

wx-downloader config show
```

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `download_dir` | `~/Downloads/wx-channels` | MP4 成品和下载记录目录 |
| `cache_dir` | `~/.cache/wx-channels` | 临时文件目录；遵循 `XDG_CACHE_HOME` |
| `quality` | `h264` | 可选 `h264`、`h265`；优先所选编码，缺失时尝试通用地址和另一编码 |
| `timeout` | `60` | 单次网络读写超时秒数，范围 1–3600 |
| `retries` | `2` | 网络错误、HTTP 429/5xx 的重试次数，范围 0–10 |
| `browser` | `auto` | 可选 `auto`、`chrome`、`chromium`、`msedge`；auto 依次尝试 Chrome、Chromium |

配置方式为 `wx-downloader config set 配置项 值`，例如：

```bash
wx-downloader config set timeout 120
wx-downloader config set retries 3
wx-downloader config set quality h265
```

视频先写入缓存目录的 `.part` 文件，校验长度和 MP4 文件头后再保存成品；缓存和成品可以位于不同磁盘。正常结束、失败或 Ctrl+C 时清理本次临时文件；强制终止进程留下的 `.part` 可手动删除。重试会重新解析链接并重新下载，目前不支持断点续传。

已有文件不会覆盖。匹配下载记录且大小一致的文件自动跳过；成品名称包含视频标题和链接哈希，避免同名冲突。成品目录中的 `.wx-*.json` 保存标题、作者和去重记录，请保留。

批量任务中单项失败会继续后续项。退出码：全部下载或跳过成功为 `0`，存在失败为 `1`，用户取消为 `130`。`--json` 输出汇总和每项结果，进度日志发送到 stderr。

## 登录与凭据

```bash
# 指定本次登录使用的浏览器和等待时长（默认 300 秒）
wx-downloader login --browser chrome --timeout 300

wx-downloader status
wx-downloader logout
```

元宝接口使用完整 Cookie，而非单个 token。CLI 在独立浏览器会话中等待 `hy_user` 和 `hy_token`，保存元宝 Cookie、浏览器登录状态和相关请求头。登录需由用户完成扫码或手机号验证；程序不读取日常浏览器配置文件。

| 文件 | 默认位置 |
| --- | --- |
| 配置 | `~/.config/wx-channels/config.json` |
| 登录凭据 | `~/.config/wx-channels/auth.json` |

可用 `WX_CHANNELS_HOME` 指定其他配置目录。凭据原子写入，文件权限为 `0600`，不打印到终端；视频号预览和媒体下载请求不携带元宝 Cookie。`status` 反映本地保存情况，服务端有效性在下载时检查；`logout` 删除本地凭据，不注销服务器会话。

元宝和视频号接口并非稳定公开 API，接口变化时可能需要更新程序。

## 升级与旧版迁移

从 PyPI 安装的工具可以这样升级：

```bash
uv tool upgrade wx-downloader
```

如果之前通过本地源码安装，或需要取消固定版本并切换到 PyPI 安装：

```bash
uv tool install --force wx-downloader --default-index https://pypi.org/simple
wx-downloader --version
```

`0.1.2` 将拼写错误的包名和命令 `wx-downloder` 更正为 `wx-downloader`。PyPI 上的旧包保留历史版本，升级旧包不会自动切换到新名称。请先安装并验证新命令，再卸载旧工具：

```bash
uv tool install wx-downloader --default-index https://pypi.org/simple
wx-downloader --version
wx-downloader status
uv tool uninstall wx-downloder
```

更早的 `wx-channels` 命令也已由 `wx-downloader` 替代；如安装过对应工具，使用 `uv tool uninstall wx-channels-cli` 移除。配置目录和 `WX_CHANNELS_HOME` 保持兼容，原登录凭据仍有效时无需重新扫码。GitHub 仓库已改名为 `QinGeneral/wx-downloader`；已有克隆可以运行 `git remote set-url origin https://github.com/QinGeneral/wx-downloader.git` 更新远程地址。

`0.1.1` 修复了登录成功后关闭浏览器时反复出现 `TargetClosedError` 的问题：请求监听使用事件自带的请求头，并在关闭前解除监听。

## 源码开发与验证

从源码安装：

```bash
git clone https://github.com/QinGeneral/wx-downloader.git
cd wx-downloader
uv sync
uv run wx-downloader --help

uv run pytest
uv run ruff check .
uv run ruff format --check .
uv build --no-sources

# 可选：真实 Chrome 回归测试，模拟登录成功后仍有请求进行的场景
WX_DOWNLOADER_BROWSER_TEST=1 uv run pytest tests/test_browser_login.py -q
```

源码项目的 uv 配置默认使用清华 PyPI 镜像；需要官方源时可执行 `uv sync --default-index https://pypi.org/simple`。这不影响通过 PyPI 包名安装 CLI。

`0.1.1` 发布前通过了 39 项常规测试和 1 项真实 Chrome 登录关闭回归测试，wheel 和源码包均完成独立安装验证。真实视频实测下载 8,155,895 字节，ffprobe 确认含 H.264 视频和 AAC 音频，时长 73.45 秒。以上真实视频验证使用改名前的 `0.1.1`，更名不改变下载流程。

## 发布流程

[GitHub Actions 发布工作流](https://github.com/QinGeneral/wx-downloader/actions/workflows/release.yml) 位于 `.github/workflows/release.yml`，已配置 PyPI Trusted Publishing：`QinGeneral / wx-downloader / release.yml / pypi`。

维护者更新 `pyproject.toml` 和 `src/wx_channels_cli/__init__.py` 中的版本，提交后创建一致的 `v<版本>` 标签并推送。构建任务检查标签、运行测试并验证发行包；独立发布任务通过 OIDC 上传，只有发布任务拥有 `id-token: write` 权限。PyPI 已发布版本不可覆盖。

[旧版 0.1.1 发布记录](https://github.com/QinGeneral/wx-downloader/actions/runs/35481356579) · [当前 PyPI 发行文件](https://pypi.org/project/wx-downloader/0.1.2/#files)

## 来源与许可

基于 [wx_channels_download](https://github.com/ltaoo/wx_channels_download) 的元宝分享链接下载流程迁移为独立 Python CLI，运行时无需 Go、微信客户端、代理抓包服务或 Cloudflare Worker。

沿用原项目的 MIT + Commons Clause 许可条件，完整文本见 [LICENSE](LICENSE)。
