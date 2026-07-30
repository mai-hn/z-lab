# TOOLBOX Modal Drive

该目录只包含 Modal Volume 的文件 API，不包含任何前端代码。

## 1. 安装并登录 Modal

```bash
pip install modal
modal setup
```

## 2. 部署 Volume API

默认使用并按需创建名为 `toolbox-drive` 的稳定版 Volume：

```bash
modal deploy modal/modal_drive.py
```

如需自定义 Volume 名称：

```bash
MODAL_DRIVE_VOLUME_NAME=my-drive modal deploy modal/modal_drive.py
```

部署完成后记录 CLI 输出的 `https://...modal.run` 地址。

## 3. 创建 Proxy Token

在 Modal Dashboard 的 Workspace 设置中创建 Web Function Proxy Token。将 Token ID
和 Token Secret 写入 Next.js 的 `.env.local`，不要使用 `NEXT_PUBLIC_` 前缀：

```dotenv
MODAL_DRIVE_API_URL=https://your-workspace--toolbox-modal-drive-drive-api.modal.run
MODAL_PROXY_TOKEN_ID=wk-...
MODAL_PROXY_TOKEN_SECRET=ws-...
MODAL_DRIVE_ACCESS_PASSWORD=change-me
```

`MODAL_DRIVE_ACCESS_PASSWORD` 是可选的。设置后，访问网盘页面时需要先输入密码；
验证成功后只写入 12 小时有效的 HttpOnly Cookie。

## API

- `GET /health`：服务状态
- `GET /files?path=/`：列出目录
- `POST /upload?path=/folder`：上传单个 multipart 文件，字段名 `file`
- `POST /folders`：创建目录，JSON `{ "path": "/folder" }`
- `PATCH /files`：重命名，JSON `{ "path": "/old", "newName": "new" }`
- `DELETE /files?path=/file&recursive=true`：删除文件或目录
- `GET /download?path=/file`：下载文件

所有端点均由 Modal `requires_proxy_auth=True` 保护，浏览器只访问 Next.js 同源代理。
