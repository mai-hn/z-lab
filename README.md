# Z-Lab

Z-Lab is a personal product site and a unified workspace for three tools:

- **Modal Drive** — metadata-first file management, resumable chunk uploads, ordered
  streaming downloads and on-demand Modal offline jobs.
- **DeepRouter** — weighted translation routing with priorities, health checks,
  fallback, logs and DeepL-compatible downstream endpoints.
- **AI Model Checker** — OpenAI-compatible model discovery, streaming generation,
  multi-turn chat and side-by-side model comparison.

The original source trees are preserved without modification in `project_old/`.

## Stack

- Next.js 16 + React 19 + TypeScript
- Python 3.12 + FastAPI
- SQLite per project
- Modal Volume for production file content
- Docker Compose for the unified runtime

## Local development

```bash
uv sync --extra dev
uv run uvicorn backend.main:app --reload --port 8000
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. Next.js proxies API, download and DeepL-compatible
routes to FastAPI.

## Docker

```bash
cp .env.example .env
docker compose up --build
```

The site is available on `http://localhost:3000`; the API and compatibility routes
are also exposed on `http://localhost:8000`.

For production Modal storage:

```bash
uv run modal setup
uv run modal deploy modal_app.py
```

Set `DRIVE_STORAGE_BACKEND=modal`, `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET`.
The API uses the Volume SDK for uploads and fallback reads; an on-demand Modal
Function starts only for offline jobs or configured direct downloads.

### Direct downloads from Modal

The optional direct-download gateway keeps file bytes off the Z-Lab server. Z-Lab
issues a short-lived signed link; the scale-to-zero Modal container validates it,
queries Z-Lab once for the ordered chunk manifest, and streams the Volume chunks
straight to the browser or WebDAV client.

Generate one shared key and configure it in the Z-Lab `.env`:

```bash
openssl rand -hex 32
```

Set the resulting value as `DRIVE_DOWNLOAD_SIGNING_KEY`, then create a Modal Secret
with the same value. `Z_LAB_API_URL` must be a public URL that the Modal container
can reach; it may point at the Next.js site because `/internal/*` is proxied:

```bash
modal secret create modal-drive-download \
  DRIVE_DOWNLOAD_SIGNING_KEY=replace-with-the-same-key \
  Z_LAB_API_URL=https://z-lab.example.com
```

Deploy the Modal App:

```bash
uv run modal deploy modal_app.py
```

Copy the URL printed for `download_gateway` into
`DRIVE_MODAL_DOWNLOAD_URL`, keep `DRIVE_DOWNLOAD_LINK_TTL_SECONDS=300`, and
restart Z-Lab:

```bash
docker compose up -d --build
```

Direct download activates only when the storage backend is `modal` and both
`DRIVE_MODAL_DOWNLOAD_URL` and `DRIVE_DOWNLOAD_SIGNING_KEY` are present.
Otherwise Z-Lab safely falls back to the original server stream.

## Important routes

| Route | Purpose |
| --- | --- |
| `/projects/drive` | File and offline download workspace |
| `/projects/router` | Translation route management |
| `/projects/models` | Model discovery and testing |
| `/api/drive/*` | Modal Drive API |
| `/api/router/api/*` | DeepRouter management API |
| `/api/models/*` | Model proxy API |
| `/dav` | WebDAV root (available on both web and API ports) |
| `/translate`, `/v2/translate`, `/v2/usage` | Original DeepRouter-compatible API |

## WebDAV

Connect a WebDAV client to `http(s)://host:port/dav`. Z-Lab supports `OPTIONS`,
`PROPFIND`, `GET`, `HEAD`, `PUT`, `MKCOL`, `DELETE`, `MOVE`, `COPY` and
`PROPPATCH`.

If `DRIVE_API_TOKEN` is empty, WebDAV is open. If it is configured, use any
username and put the token in the WebDAV password field. Bearer authentication
and the `X-API-Token` header remain available for API clients.

WebDAV `PUT` writes files larger than 8 MiB as ordered chunks without a
persistent local file cache. `GET` redirects to a signed Modal link when direct
download is configured; otherwise it reads chunks through Z-Lab. Both paths return
`Content-Length`, `X-File-Size`, `ETag` and `Last-Modified`.

The translation router keeps its public compatibility endpoint at
`http(s)://host:port/translate`.

See [docs/architecture.md](docs/architecture.md) for boundaries and the extension model.
