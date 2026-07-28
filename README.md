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
The API uses the Volume SDK for normal reads and writes; an on-demand Modal Function
starts only for offline downloads.

## Important routes

| Route | Purpose |
| --- | --- |
| `/projects/drive` | File and offline download workspace |
| `/projects/router` | Translation route management |
| `/projects/models` | Model discovery and testing |
| `/api/drive/*` | Modal Drive API |
| `/api/router/api/*` | DeepRouter management API |
| `/api/models/*` | Model proxy API |
| `/translate`, `/v2/translate`, `/v2/usage` | Original DeepRouter-compatible API |

See [docs/architecture.md](docs/architecture.md) for boundaries and the extension model.
