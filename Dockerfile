# syntax=docker/dockerfile:1.7

FROM node:22-alpine AS frontend-deps
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

FROM frontend-deps AS frontend-build
COPY frontend/ ./
ARG API_INTERNAL_URL=http://api:8000
ENV NEXT_TELEMETRY_DISABLED=1 \
    API_INTERNAL_URL=${API_INTERNAL_URL}
RUN npm run build

FROM node:22-alpine AS frontend-runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs
COPY --from=frontend-build --chown=nextjs:nodejs /app/frontend/.next/standalone ./
COPY --from=frontend-build --chown=nextjs:nodejs /app/frontend/.next/static ./.next/static
COPY --from=frontend-build --chown=nextjs:nodejs /app/frontend/public ./public
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]

FROM python:3.12-slim AS backend-runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    Z_LAB_DATA_ROOT=/data
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends aria2 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9.22 /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend ./backend
COPY modal_app.py ./
RUN mkdir -p /data && chown -R 1000:1000 /data /app
USER 1000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
