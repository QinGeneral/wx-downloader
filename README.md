# wx-downloder

独立 Python CLI：打开腾讯元宝登录、保存登录凭据、解析微信视频号分享链接并下载 MP4。基于原项目 [wx_channels_download](https://github.com/ltaoo/wx_channels_download) 的元宝分享链接下载流程迁移；运行时无需 Go、微信客户端、代理抓包服务或 Cloudflare Worker。

## 安装

需要 Python 3.10+，以及 Chrome 或 Playwright Chromium。

```bash
uv tool install wx-downloder
wx-downloder --help
```

固定安装本次版本：`uv tool install wx-downloder==0.1.1`。也支持 `python -m pip install wx-downloder`。

如未安装 Chrome，安装 Playwright Chromium：

```bash
uv tool run --from playwright playwright install chromium
```

源码开发安装：

```bash
git clone https://github.com/QinGeneral/wx-downloder.git
cd wx-downloder
uv sync
uv run wx-downloder --help
```

从旧版 `wx-channels` 更新：先安装新版并确认 `wx-downloder --version` 输出 `0.1.1`，再运行 `uv tool uninstall wx-channels-cli` 移除旧命令。配置目录、`WX_CHANNELS_HOME` 环境变量和登录凭据位置保持兼容，已经登录的用户无需再次扫码。

0.1.1 修复登录成功后浏览器关闭时请求回调反复抛出 `TargetClosedError`：请求监听使用本地缓存的请求头，并在关闭前解除监听。

项目默认使用清华 PyPI 镜像以改善国内安装速度；需要官方源时可执行 `uv sync --default-index https://pypi.org/simple`。

## 登录和下载

```bash
# 启动独立浏览器窗口，扫码或手机号登录，检测到凭据后自动保存
wx-downloder login

# 单个链接；未保存登录凭据时会自动打开登录窗口
wx-downloder download 'https://weixin.qq.com/sph/实际分享ID'

# 多个链接 / JSON 文件 / 内联 JSON
wx-downloder download 'https://weixin.qq.com/sph/ID1' 'https://weixin.qq.com/sph/ID2'
wx-downloder download --input examples/links.json
wx-downloder download links.json
wx-downloder download '["https://weixin.qq.com/sph/ID1", {"url":"https://weixin.qq.com/sph/ID2"}]'
cat links.json | wx-downloder download - --no-login --json

# 不传参数：终端交互输入；管道输入则读取标准输入
wx-downloder download
```

必须使用微信分享生成的 `https://weixin.qq.com/sph/...` 链接。会自动去除分享参数和重复项。暂不支持公众号文章、直播、图集或微信内部短口令。

JSON 支持字符串数组、带 `url` / `share_url` / `shareUrl` / `sourceUrl` / `link` 字段的对象，以及 `links` / `urls` / `videos` / `items` / `data` 包装的列表。文件支持 UTF-8 和 UTF-8 BOM。示例链接需替换成真实链接。开始下载前验证全部输入，避免错格式时弹出浏览器。

## 目录配置

```bash
# 成品目录，默认 ~/Downloads/wx-channels
wx-downloder config set download_dir '/Volumes/Data/微信视频'

# 临时下载缓存目录，默认 ~/.cache/wx-channels（遵循 XDG_CACHE_HOME）
wx-downloder config set cache_dir '/Volumes/Data/视频缓存'

# 单次覆盖配置；支持缓存和成品在不同磁盘
wx-downloder download --input links.json --output './videos' --cache-dir './cache'

wx-downloder config set quality h265
wx-downloder config set timeout 120
wx-downloder config set retries 2
wx-downloder config set browser chrome
wx-downloder config show
wx-downloder status
wx-downloder logout
```

`quality` 默认为 h264；优先所选编码，缺失时尝试通用地址和另一编码。`timeout` 是单次网络读写超时（秒），`retries` 是网络错误、HTTP 429/5xx 的重试次数（0–10）。重试重新解析链接并重新下载，不续传。批量任务中某个视频失败会继续后续项，并返回退出码 1；全部下载或跳过成功返回 0；取消返回 130。

视频先写入缓存目录 `.part` 文件，校验长度和 MP4 文件头后再保存成品。正常结束、失败或 Ctrl+C 时清理本次临时文件。强制终止进程留下的 `.part` 可手动删除。已有文件不会覆盖；匹配下载记录且大小一致的文件自动跳过。成品名称包含视频标题和链接哈希，避免同名冲突；成品目录中的 `.wx-*.json` 保存标题、作者和去重记录，请保留。

## 登录凭据

元宝接口实际使用完整 Cookie，而非单个 token。CLI 在独立浏览器上下文中等待 `hy_user` 和 `hy_token`，保存适用于元宝的 Cookie、浏览器登录状态和相关请求头。保存后关闭本次浏览器，不读取日常浏览器配置文件。

配置默认位于 `~/.config/wx-channels/config.json`，凭据位于同目录的 `auth.json`。可用 `WX_CHANNELS_HOME` 指定其他配置目录。凭据原子写入，文件权限为 `0600`，不打印到终端；下载 CDN 和视频号预览请求不携带元宝 Cookie。`logout` 删除本地凭据，不注销服务器会话。`status` 只反映本地保存情况；服务端凭据过期需重新 `login`。

使用 [Playwright 浏览器登录状态保存机制](https://playwright.dev/python/docs/auth)。元宝和视频号接口并非稳定公开 API，接口或登录方式变化时可能需要更新。真实扫码必须由用户完成；自动测试使用模拟接口，不等同于真实账号端到端验证。

## 开发验证

```bash
uv sync
uv run pytest
uv run ruff check .
uv build

# 可选：真实 Chrome 回归测试，模拟登录成功后仍有请求进行的场景
WX_DOWNLODER_BROWSER_TEST=1 uv run pytest tests/test_browser_login.py -q
```

原项目许可证为 MIT + Commons Clause，保留在 `LICENSE`；本项目沿用该许可条件。

验收记录：39 项常规自动化测试和 1 项真实 Chrome 登录关闭回归测试通过，Ruff 检查及格式检查通过，wheel/源码包构建通过。使用源项目已有凭据实测下载了一个 8,155,895 字节的视频，ffprobe 确认含 H.264 视频流和 AAC 音频流，时长 73.45 秒。该实测不替代用户首次扫码登录；新项目未预填源项目的凭据。

## 发布流程

发布使用 GitHub Actions 的 `.github/workflows/release.yml`，绑定 PyPI Trusted Publisher：`QinGeneral / wx-downloder / release.yml / pypi`。构建任务检查版本标签、运行测试、构建 wheel 和源码包并验证 CLI；独立发布任务通过 OIDC 上传，只有发布任务拥有 `id-token: write` 权限。

维护者更新版本并提交后，创建与版本一致的 `v<版本>` 标签并推送即可发布。PyPI 版本不可覆盖。PyPI 页面：[wx-downloder](https://pypi.org/project/wx-downloder/)。
