"""Accès à la base SQLite (asynchrone, via aiosqlite).

Chaque module crée ses propres tables au chargement : `await bot.db.ensure(SCHEMA)`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aiosqlite


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        await self.conn.execute("PRAGMA foreign_keys = ON")

    async def close(self) -> None:
        if self.conn is not None:
            await self.conn.close()
            self.conn = None

    def _db(self) -> aiosqlite.Connection:
        if self.conn is None:
            raise RuntimeError("base non connectée")
        return self.conn

    async def ensure(self, schema: str) -> None:
        await self._db().executescript(schema)
        await self._db().commit()

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        """Une écriture ; renvoie le nombre de lignes touchées."""
        cur = await self._db().execute(sql, params)
        await self._db().commit()
        return cur.rowcount

    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> tuple | None:
        async with self._db().execute(sql, params) as cur:
            return await cur.fetchone()

    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple]:
        async with self._db().execute(sql, params) as cur:
            return list(await cur.fetchall())
