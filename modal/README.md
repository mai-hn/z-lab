# TOOLBOX Modal Drive

Modal 仅负责暴露网盘文件 API，Modal Volume 仅保存文件。渠道、模型、请求记录、
网盘文件索引和视频元信息数据库都保存在运行 Next.js 的本机。

## 1. 安装并登录 Modal

```bash
pip install modal
modal setup
```

## 2. 首次部署 Python 网盘 API

默认创建并使用名为 `toolbox-drive` 的持久化 Volume：

```bash
modal deploy modal/modal_drive.py
```

自定义 Volume 名称：

```bash
MODAL_DRIVE_VOLUME_NAME=my-drive modal deploy modal/modal_drive.py
```

部署完成后记录 CLI 输出的 `https://...modal.run` 地址。以后修改
`modal/modal_drive.py` 后，需要再次执行相同的 `modal deploy` 命令更新服务。

## 3. 可选：把 rclone 网盘接入 Cloud

先在本机完成 rclone 配置并确认其中的远端可用：

```powershell
rclone config
rclone listremotes
rclone lsd onedrive:
```

部署时只需传入配置文件路径。PowerShell 示例：

```powershell
$env:MODAL_RCLONE_CONFIG_PATH="$env:APPDATA\rclone\rclone.conf"
modal deploy modal/modal_drive.py
```

Modal 会在运行时执行 `rclone listremotes`，自动读取配置中的全部 remote。如果
`rclone.conf` 使用了配置文件加密，还需要在部署时设置：

```powershell
$env:MODAL_RCLONE_CONFIG_PASSWORD="your-rclone-config-password"
```

部署脚本读取本机配置文件后，会创建或更新名为 `toolbox-rclone-config` 的 Modal
Secret，并将其注入 Web API 和离线下载 worker。配置文件不会写入 Modal Volume，
也不需要写入 Next.js 的 `.env.local`。以后使用同一命令重新部署时，该命名 Secret
会同步为最新的本机配置。
部署结束后可以清除当前 PowerShell 会话中的临时变量：

```powershell
Remove-Item Env:MODAL_RCLONE_CONFIG_PATH
Remove-Item Env:MODAL_RCLONE_CONFIG_PASSWORD -ErrorAction SilentlyContinue
```

网盘根目录始终显示保留目录 `/Cloud`。Cloud 下一层为配置文件中的全部 remote，
例如 `onedrive:` 和 `gdrive:` 分别显示为 `/Cloud/onedrive` 和 `/Cloud/gdrive`。
未传配置时进入 Cloud 会返回明确的 503 配置错误。`/Cloud` 及 remote 入口文件夹
不能删除、重命名、复制或移动。

## 4. 创建 Proxy Token

在 Modal Dashboard 的 Workspace 设置中创建 Web Function Proxy Token，然后写入
Next.js 的 `.env.local`：

```dotenv
MODAL_DRIVE_API_URL=https://your-workspace--toolbox-modal-drive-drive-api.modal.run
MODAL_PROXY_TOKEN_ID=wk-...
MODAL_PROXY_TOKEN_SECRET=ws-...
MODAL_DRIVE_ACCESS_PASSWORD=change-me
```

`MODAL_DRIVE_ACCESS_PASSWORD` 可选。设置后，网盘页面使用 12 小时有效的
HttpOnly Cookie 保护访问。

## 数据边界

- Modal Volume：保存根目录中除 `/Cloud` 外的原始文件和文件夹。
- rclone remotes：分别映射到 `/Cloud/<remote名称>`；配置通过 Modal Secret 注入。
- Modal Dict `toolbox-modal-drive-download-jobs`：只保存离线任务进度与停止标记；
  条目无读写 7 天后自动过期，不作为业务数据库。
- Modal Dict `toolbox-modal-drive-transfer-jobs`：保存复制和移动任务的进度与停止标记，
  生命周期与离线任务相同。
- `data/modal_drive.sqlite3`：本机网盘索引、操作事件、视频元信息。
- `data/model_tester.sqlite3`：本机模型渠道、模型和请求日志。
- `data/.model-tester.key`：自动生成的本机渠道密钥加密键。

可以通过 `TOOLBOX_DATA_DIR` 把本机数据库目录改到其他绝对或相对路径。

## Modal API

- `GET /health`：服务状态。
- `GET /files?path=/`：列出目录。
- `POST /upload?path=/folder`：上传文件。
- `POST /folders`：创建目录。
- `PATCH /files`：重命名。
- `DELETE /files?path=/file&recursive=true`：删除文件或目录。
- `POST /copy`：提交后台复制任务，JSON 为
  `{"sourcePath":"/a","destinationPath":"/Cloud/onedrive/a"}`。
- `POST /move`：提交后台移动任务，请求格式与复制相同。
- `GET /transfer?jobId=...`：查询复制或移动状态、字节进度、文件数和速度。
- `DELETE /transfer?jobId=...`：停止正在执行的复制或移动任务。
- `GET /download?path=/file`：下载文件。
- `POST /offline-download`：提交 1–50 个 HTTP(S) 直链，由后台 worker 串行下载。
- `GET /offline-download?jobId=...`：轮询状态、当前文件、字节进度、速度和结果。
- `DELETE /offline-download?jobId=...`：请求停止任务并清理当前 `.part` 临时文件；
  已经完成并提交到 Volume 的文件会保留。
- `GET /metadata?path=/video.mp4`：使用 ffprobe 返回视频元信息；结果由 Next.js 写入本机数据库。

离线下载 worker 的 `max_containers=1`，所以同一批链接按输入顺序处理，同时提交的
多个批次也会排队。任务最长运行 24 小时；同名文件会自动添加数字序号。worker
每下载 1 MB 并且距离上次更新至少约 0.75 秒时刷新进度和检查停止标记。
重新部署前已经提交、任务 ID 以 `fc-` 开头的旧任务无法补充字节进度，但新 API
仍可查询其运行状态，并可通过 `DELETE /offline-download` 强制停止。

所有 Modal 端点均由 `requires_proxy_auth=True` 保护，浏览器只访问 Next.js 同源代理。

进入具体 remote 后，上传、下载、建目录、重命名、删除和离线下载均可使用。复制
或移动只要源或目标任一端位于 `/Cloud/<remote名称>/...`，Python API 就调用 rclone
的 `copyto`；这也支持两个不同 remote 之间传输。移动在复制成功后再删除源。目标
已存在时返回 HTTP 409，不自动覆盖。

复制和移动由独立 worker 串行处理，并通过 rclone JSON stats 更新本机页面的字节
进度、文件数量和速度。为了保证停止移动任务时不丢失源数据，移动实现为“完整复制
并提交目标，再删除源”；在复制阶段停止不会删除源，并会显式清理本任务尚未完成的
目标文件或目录。
