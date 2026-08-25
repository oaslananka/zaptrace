"""SQLite-backed persistent cache for BOM and distributor intelligence."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from zaptrace.supply.contracts import (
    BomProviderResult,
    CacheMetadata,
    CacheStatus,
)


class SqliteSupplyCache:
    """Persistent SQLite cache for manufacturer and distributor part queries."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = Path.home() / ".zaptrace" / "supply_cache.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path), timeout=10.0)

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS supply_cache (
                    mpn TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    data TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    PRIMARY KEY (mpn, provider)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mpn_provider ON supply_cache (mpn, provider)"
            )
            conn.commit()

    def get(
        self,
        mpn: str,
        provider: str = "",
        allow_stale: bool = True,
    ) -> BomProviderResult | None:
        """Lookup a cached part.

        If expired and *allow_stale* is True, returns result with CacheStatus.STALE.
        If expired and *allow_stale* is False, returns None.
        """
        now = datetime.now(UTC)
        if provider:
            query = "SELECT data, fetched_at, expires_at, provider FROM supply_cache WHERE mpn = ? AND provider = ?"
            params = (mpn.strip().upper(), provider)
        else:
            query = (
                "SELECT data, fetched_at, expires_at, provider "
                "FROM supply_cache WHERE mpn = ? ORDER BY fetched_at DESC LIMIT 1"
            )
            params = (mpn.strip().upper(),)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            row = cursor.fetchone()
            if not row:
                return None

            data_str, fetched_at_str, expires_at_str, prov_name = row
            try:
                data = json.loads(data_str)
                expires_at = datetime.fromisoformat(expires_at_str)
                is_stale = now > expires_at

                if is_stale and not allow_stale:
                    return None

                cache_meta = CacheMetadata(
                    status=CacheStatus.STALE if is_stale else CacheStatus.FRESH,
                    source=f"sqlite:{prov_name}",
                    fetched_at=fetched_at_str,
                    offline=True,
                )
                data["cache"] = cache_meta.model_dump()
                return BomProviderResult.model_validate(data)
            except (json.JSONDecodeError, ValueError, KeyError):
                return None

    def put(
        self,
        result: BomProviderResult,
        ttl_seconds: int = 86400,
    ) -> None:
        """Save a lookup result to the cache."""
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)
        data = result.model_dump(mode="json")
        mpn_key = result.mpn.strip().upper()

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO supply_cache (mpn, provider, data, fetched_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    mpn_key,
                    result.provider,
                    json.dumps(data),
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )
            conn.commit()

    def clear(self) -> int:
        """Clear all cached entries. Returns number of deleted rows."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM supply_cache")
            count = cursor.rowcount
            conn.commit()
            return count

    def stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*), COUNT(DISTINCT provider) FROM supply_cache")
            row = cursor.fetchone()
            total = row[0] if row else 0
            providers = row[1] if row else 0

            now_iso = datetime.now(UTC).isoformat()
            cursor.execute("SELECT COUNT(*) FROM supply_cache WHERE expires_at > ?", (now_iso,))
            fresh_row = cursor.fetchone()
            fresh = fresh_row[0] if fresh_row else 0

            return {
                "total_entries": total,
                "fresh_entries": fresh,
                "stale_entries": total - fresh,
                "providers": providers,
                "db_path": str(self.db_path),
            }
