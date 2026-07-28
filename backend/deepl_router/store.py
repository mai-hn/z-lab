from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


PROVIDERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS providers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  api_key TEXT NOT NULL DEFAULT '',
  api_secret TEXT NOT NULL DEFAULT '',
  region TEXT NOT NULL DEFAULT '',
  priority INTEGER NOT NULL DEFAULT 100,
  weight INTEGER NOT NULL DEFAULT 1,
  enabled INTEGER NOT NULL DEFAULT 1,
  timeout_seconds INTEGER NOT NULL DEFAULT 20,
  last_status TEXT NOT NULL DEFAULT 'unknown',
  last_latency_ms INTEGER,
  last_error TEXT,
  quota TEXT,
  quota_checked_at TEXT,
  quota_error TEXT,
  quota_limit REAL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

SCHEMA = PROVIDERS_SCHEMA + """
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS request_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT NOT NULL,
  route TEXT NOT NULL,
  downstream_request TEXT NOT NULL,
  upstream_attempts TEXT NOT NULL DEFAULT '[]',
  response_body TEXT,
  provider TEXT,
  status TEXT NOT NULL,
  latency_ms INTEGER,
  error TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_request_logs_created_at ON request_logs(created_at DESC);
CREATE TABLE IF NOT EXISTS provider_health_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider_id INTEGER NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('healthy', 'unhealthy')),
  latency_ms INTEGER,
  error TEXT,
  source TEXT NOT NULL DEFAULT 'call',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_provider_health_events_provider_created_at ON provider_health_events(provider_id, id DESC);
"""


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript(SCHEMA)
            self._ensure_provider_columns(conn)
            self._migrate_usage_to_quota(conn)
            self._rebuild_providers_if_needed(conn)
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('routing_mode', 'weighted')")
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('fallback_enabled', 'true')")
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('downstream_key', '')")

    @staticmethod
    def _rebuild_providers_if_needed(conn: sqlite3.Connection) -> None:
        definition = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'providers'").fetchone()["sql"]
        # 注意列名 quota_checked_at 含 "check" 子串，须匹配 CHECK( 约束语法
        if "CHECK(" not in definition.upper().replace(" ", ""):
            return
        conn.execute("ALTER TABLE providers RENAME TO providers_legacy")
        conn.executescript(PROVIDERS_SCHEMA)
        legacy_columns = {row["name"] for row in conn.execute("PRAGMA table_info(providers_legacy)").fetchall()}
        new_columns = {row["name"] for row in conn.execute("PRAGMA table_info(providers)").fetchall()}
        columns = [name for name in legacy_columns & new_columns]
        quoted = ",".join(columns)
        conn.execute(f"INSERT INTO providers ({quoted}) SELECT {quoted} FROM providers_legacy")
        conn.execute("DROP TABLE providers_legacy")

    @staticmethod
    def _ensure_provider_columns(conn: sqlite3.Connection) -> None:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(providers)").fetchall()}
        for name, definition in {
            "api_secret": "TEXT NOT NULL DEFAULT ''",
            "region": "TEXT NOT NULL DEFAULT ''",
            "quota": "TEXT",
            "quota_checked_at": "TEXT",
            "quota_error": "TEXT",
            "quota_limit": "REAL",
        }.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE providers ADD COLUMN {name} {definition}")

    @staticmethod
    def _migrate_usage_to_quota(conn: sqlite3.Connection) -> None:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(providers)").fetchall()}
        if "usage_character_count" not in existing:
            return
        rows = conn.execute(
            "SELECT id, usage_character_count, usage_character_limit, usage_checked_at FROM providers WHERE quota IS NULL AND usage_character_count IS NOT NULL"
        ).fetchall()
        for row in rows:
            quota = json.dumps({"type": "characters", "used": row["usage_character_count"], "limit": row["usage_character_limit"]})
            conn.execute("UPDATE providers SET quota = ?, quota_checked_at = ? WHERE id = ?", (quota, row["usage_checked_at"], row["id"]))

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def row_to_dict(row: sqlite3.Row, reveal_key: bool = False) -> dict[str, Any]:
        from .upstreams import quota_exceeded

        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        if item.get("quota"):
            try:
                item["quota"] = json.loads(item["quota"])
            except ValueError:
                item["quota"] = None
        item["quota_exceeded"] = quota_exceeded(item)
        if not reveal_key:
            key = item.pop("api_key", "")
            item.pop("api_secret", None)
            item["key_hint"] = ("•" * 8 + key[-4:]) if key else "未设置"
        return item

    def providers(self, reveal_key: bool = False) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM providers ORDER BY priority ASC, id ASC").fetchall()
        items = [self.row_to_dict(row, reveal_key) for row in rows]
        histories = self.health_history([item["id"] for item in items])
        for item in items:
            item["health_history"] = histories.get(item["id"], [])
        return items

    def provider(self, provider_id: int, reveal_key: bool = True) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
        return self.row_to_dict(row, reveal_key) if row else None

    def create_provider(self, payload: dict[str, Any]) -> dict[str, Any]:
        fields = ("name", "kind", "endpoint", "api_key", "api_secret", "region", "priority", "weight", "enabled", "timeout_seconds", "quota_limit")
        with self.connection() as conn:
            cursor = conn.execute(
                f"INSERT INTO providers ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",
                [self._field_value(payload, field) for field in fields],
            )
            row = conn.execute("SELECT * FROM providers WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return self.row_to_dict(row)

    @staticmethod
    def _field_value(payload: dict[str, Any], field: str) -> Any:
        if field in {"api_secret", "region"}:
            return payload.get(field, "") or ""
        if field == "quota_limit":
            return payload.get(field)
        return payload[field]

    def create_providers(self, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        fields = ("name", "kind", "endpoint", "api_key", "api_secret", "region", "priority", "weight", "enabled", "timeout_seconds", "quota_limit")
        with self.connection() as conn:
            ids = []
            for payload in payloads:
                cursor = conn.execute(
                    f"INSERT INTO providers ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",
                    [self._field_value(payload, field) for field in fields],
                )
                ids.append(cursor.lastrowid)
            rows = conn.execute(
                f"SELECT * FROM providers WHERE id IN ({','.join('?' for _ in ids)}) ORDER BY id ASC", ids
            ).fetchall()
        return [self.row_to_dict(row) for row in rows]

    def update_provider(self, provider_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {"name", "kind", "endpoint", "api_key", "api_secret", "region", "priority", "weight", "enabled", "timeout_seconds", "quota_limit"}
        # quota_limit 允许显式置 None（清除限额），其余字段忽略 None
        changes = {key: value for key, value in payload.items() if key in allowed and (value is not None or key == "quota_limit")}
        if not changes:
            return self.provider(provider_id, reveal_key=False)
        assignments = ", ".join(f"{key} = ?" for key in changes)
        with self.connection() as conn:
            conn.execute(f"UPDATE providers SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (*changes.values(), provider_id))
            row = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
        return self.row_to_dict(row) if row else None

    def delete_provider(self, provider_id: int) -> bool:
        with self.connection() as conn:
            return conn.execute("DELETE FROM providers WHERE id = ?", (provider_id,)).rowcount > 0

    @staticmethod
    def _unique_provider_ids(provider_ids: list[int]) -> list[int]:
        return list(dict.fromkeys(provider_ids))

    def disable_unhealthy_providers(self, provider_ids: list[int]) -> list[int]:
        ids = self._unique_provider_ids(provider_ids)
        placeholders = ",".join("?" for _ in ids)
        with self.connection() as conn:
            rows = conn.execute(
                f"SELECT id FROM providers WHERE id IN ({placeholders}) AND last_status = 'unhealthy' AND enabled = 1",
                ids,
            ).fetchall()
            affected_ids = [row["id"] for row in rows]
            if affected_ids:
                affected_placeholders = ",".join("?" for _ in affected_ids)
                conn.execute(
                    f"UPDATE providers SET enabled = 0, updated_at = CURRENT_TIMESTAMP WHERE id IN ({affected_placeholders})",
                    affected_ids,
                )
        return affected_ids

    def delete_unhealthy_providers(self, provider_ids: list[int]) -> list[int]:
        ids = self._unique_provider_ids(provider_ids)
        placeholders = ",".join("?" for _ in ids)
        with self.connection() as conn:
            rows = conn.execute(
                f"SELECT id FROM providers WHERE id IN ({placeholders}) AND last_status = 'unhealthy'",
                ids,
            ).fetchall()
            affected_ids = [row["id"] for row in rows]
            if affected_ids:
                affected_placeholders = ",".join("?" for _ in affected_ids)
                conn.execute(f"DELETE FROM providers WHERE id IN ({affected_placeholders})", affected_ids)
        return affected_ids

    def set_health(self, provider_id: int, status: str, latency_ms: int | None, error: str | None = None, source: str = "call") -> None:
        with self.connection() as conn:
            conn.execute("UPDATE providers SET last_status = ?, last_latency_ms = ?, last_error = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (status, latency_ms, error, provider_id))
            conn.execute(
                "INSERT INTO provider_health_events(provider_id, status, latency_ms, error, source) VALUES (?, ?, ?, ?, ?)",
                (provider_id, status, latency_ms, error, source),
            )

    def health_history(self, provider_ids: list[int], limit: int = 12) -> dict[int, list[dict[str, Any]]]:
        if not provider_ids:
            return {}
        placeholders = ",".join("?" for _ in provider_ids)
        with self.connection() as conn:
            rows = conn.execute(
                f"SELECT provider_id, status, latency_ms, source, created_at FROM provider_health_events WHERE provider_id IN ({placeholders}) ORDER BY id DESC",
                provider_ids,
            ).fetchall()
        histories: dict[int, list[dict[str, Any]]] = {provider_id: [] for provider_id in provider_ids}
        for row in rows:
            history = histories[row["provider_id"]]
            if len(history) < limit:
                history.append(dict(row))
        return histories

    def set_quota(self, provider_id: int, quota: dict[str, Any] | None, error: str | None = None) -> None:
        with self.connection() as conn:
            conn.execute(
                """UPDATE providers SET quota = ?, quota_checked_at = CURRENT_TIMESTAMP,
                   quota_error = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                (json.dumps(quota, ensure_ascii=False) if quota is not None else None, error, provider_id),
            )

    def request_stats(self) -> dict[str, Any]:
        with self.connection() as conn:
            total = conn.execute("SELECT COUNT(*) AS n FROM request_logs").fetchone()["n"]
            row = conn.execute(
                """SELECT COUNT(*) AS total,
                          COALESCE(SUM(status = 'success'), 0) AS success,
                          AVG(latency_ms) AS avg_latency
                   FROM request_logs WHERE created_at >= datetime('now', '-1 day')"""
            ).fetchone()
        return {
            "total": total,
            "last_24h": row["total"],
            "success_24h": row["success"],
            "failed_24h": row["total"] - row["success"],
            "avg_latency_24h": round(row["avg_latency"]) if row["avg_latency"] is not None else None,
        }

    def settings(self) -> dict[str, str]:
        with self.connection() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def update_settings(self, values: dict[str, Any]) -> dict[str, str]:
        allowed = {"routing_mode", "fallback_enabled", "downstream_key"}
        with self.connection() as conn:
            for key, value in values.items():
                if key in allowed and value is not None:
                    conn.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))
        return self.settings()

    def create_request_log(self, *, request_id: str, route: str, downstream_request: dict[str, Any], upstream_attempts: list[dict[str, Any]], response_body: dict[str, Any] | None, provider: str | None, status: str, latency_ms: int | None, error: str | None = None) -> int:
        with self.connection() as conn:
            cursor = conn.execute(
                """INSERT INTO request_logs(request_id, route, downstream_request, upstream_attempts, response_body, provider, status, latency_ms, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (request_id, route, json.dumps(downstream_request, ensure_ascii=False), json.dumps(upstream_attempts, ensure_ascii=False), json.dumps(response_body, ensure_ascii=False) if response_body is not None else None, provider, status, latency_ms, error),
            )
        return int(cursor.lastrowid)

    @staticmethod
    def log_row_to_dict(row: sqlite3.Row, detail: bool = False) -> dict[str, Any]:
        item = dict(row)
        for field in ("downstream_request", "upstream_attempts", "response_body"):
            if item[field] is not None:
                item[field] = json.loads(item[field])
        if not detail:
            request = item.pop("downstream_request")
            item.pop("upstream_attempts", None)
            item.pop("response_body", None)
            item["text_preview"] = str(request.get("text", ""))[:100]
            item["attempt_count"] = len(json.loads(row["upstream_attempts"]))
        return item

    def request_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM request_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [self.log_row_to_dict(row) for row in rows]

    def request_log(self, log_id: int) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM request_logs WHERE id = ?", (log_id,)).fetchone()
        return self.log_row_to_dict(row, detail=True) if row else None
