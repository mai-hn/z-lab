# Z-Lab architecture

## Runtime boundary

```text
Browser
  │
  ├─ Next.js pages and server proxy :3000
  │      ├─ /api/drive/*  ───────────────┐
  │      ├─ /api/router/*                │
  │      ├─ /api/models/*                ▼
  │      └─ /translate + /v2/*     FastAPI :8000
  │                                   │
  │                 ┌─────────────────┼─────────────────┐
  │                 ▼                 ▼                 ▼
  │           Modal Drive         DeepRouter      Model proxy
  │            SQLite +           SQLite +          stateless
  │         Modal Volume API      upstreams
```

Next.js owns presentation and browser interaction. FastAPI owns service integration,
validation and persistence. Each project has its own API prefix and database boundary,
so a new project does not need to share domain tables with existing tools.

## File storage invariants

1. A file node is metadata. Its content is represented by a content record and an
   ordered chunk manifest.
2. Rename and move update only node metadata. Copy creates another reference to the
   same content record.
3. The final reference deletion removes every manifest chunk through the configured
   storage adapter. With the Modal adapter this is a Modal Volume API operation.
4. Browser uploads larger than 8 MiB use 4 MiB resumable chunks. Modal offline jobs
   also emit an ordered manifest for files larger than 8 MiB.
5. Download streams manifest entries in order and supports HTTP Range. `Content-Length`,
   `X-File-Size` and `X-Chunk-Count` allow browsers and clients to show progress.

## Adding another project

1. Add a FastAPI router or mounted sub-application under `backend/`.
2. Register its public metadata in `backend/registry.py`.
3. Add its presentation metadata to `frontend/src/lib/projects.ts`.
4. Add a page under `frontend/src/app/projects/<slug>/page.tsx`.
5. Add an icon and accent token if the existing three accents are not sufficient.

Keep a project database private to that project. Shared infrastructure belongs in
`backend/` or `frontend/src/components`; domain logic stays inside the project module.
