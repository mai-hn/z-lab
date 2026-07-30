# TOOLBOX

基于 Next.js 的个人工具集合。模型测试业务和数据库在本机运行；Modal 只提供
Volume 网盘文件 API。

## 本地启动

需要 Node.js 22.5 或更高版本（项目使用 Node 内置 SQLite）。

```bash
npm install
npm run dev
```

打开 [http://localhost:3000](http://localhost:3000)。

## 本机数据库

默认保存在项目根目录的 `data/`，该目录不会提交到 Git：

- `model_tester.sqlite3`：模型渠道、渠道模型和请求日志。
- `modal_drive.sqlite3`：Modal 网盘文件索引、操作事件和视频元信息。
- `.model-tester.key`：自动生成的渠道 API Key 加密密钥。

可以在 `.env.local` 中设置 `TOOLBOX_DATA_DIR` 修改数据库目录，或者设置
`MODEL_TESTER_DATABASE_KEY` 使用固定的渠道密钥加密口令。修改加密口令后，既有
渠道密钥将无法解密。

## Modal 网盘

首次部署仍然使用 Python：

```bash
modal deploy modal/modal_drive.py
```

Modal Volume 保存本地文件；可在部署时传入 `rclone.conf`，配置中的全部 remote
会自动显示为 `/Cloud/<remote名称>`。Modal Python API 负责列目录、上传、下载、复制、移动、离线
下载、重命名、删除，以及通过 ffprobe 返回视频元信息；源或目标位于 `/Cloud` 时
文件操作使用 rclone。Next.js 将索引和元信息写入本机 `modal_drive.sqlite3`。
离线下载任务在 Modal 后台执行，同一批以及同时提交的多个批次都会串行处理。
Next.js 会轮询 Modal 的任务 API，在本机页面显示当前文件、字节进度、百分比和
速度，并可停止离线下载、复制或移动任务；已完成的文件会保留。

完整配置见 [`modal/README.md`](modal/README.md) 和 [`.env.example`](.env.example)。
