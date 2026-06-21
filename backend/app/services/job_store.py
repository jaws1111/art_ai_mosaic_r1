"""SQLite persistence for mosaic jobs and tile state."""

from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

from app.models.mosaic import JobStatus, TileState, TileStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    prompt TEXT NOT NULL,
    style_anchor TEXT NOT NULL,
    canvas_json TEXT NOT NULL,
    grid_json TEXT NOT NULL,
    run_path TEXT NOT NULL,
    outputs_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tiles (
    job_id TEXT NOT NULL,
    row INTEGER NOT NULL,
    col INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    status TEXT NOT NULL,
    tile_path TEXT,
    error TEXT,
    PRIMARY KEY (job_id, row, col),
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);
"""


class JobStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    async def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA)
            try:
                await db.execute(
                    "ALTER TABLE jobs ADD COLUMN regions_json TEXT NOT NULL DEFAULT '[]'"
                )
            except aiosqlite.OperationalError:
                pass
            for ddl in (
                "ALTER TABLE jobs ADD COLUMN display_name TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE jobs ADD COLUMN run_quality_check INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE jobs ADD COLUMN include_ai_critique INTEGER NOT NULL DEFAULT 0",
            ):
                try:
                    await db.execute(ddl)
                except aiosqlite.OperationalError:
                    pass
            await db.commit()

    async def create_job(
        self,
        job_id: str,
        prompt: str,
        style_anchor: str,
        canvas_json: str,
        grid_json: str,
        run_path: str,
        created_at: str,
        regions_json: str = "[]",
        display_name: str = "",
        run_quality_check: bool = False,
        include_ai_critique: bool = False,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO jobs (id, status, prompt, style_anchor, canvas_json, grid_json,
                                  run_path, outputs_json, regions_json, display_name,
                                  run_quality_check, include_ai_critique, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, '{}', ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    JobStatus.PENDING.value,
                    prompt,
                    style_anchor,
                    canvas_json,
                    grid_json,
                    run_path,
                    regions_json,
                    display_name,
                    int(run_quality_check),
                    int(include_ai_critique),
                    created_at,
                    created_at,
                ),
            )
            await db.commit()

    async def update_display_name(self, job_id: str, display_name: str, updated_at: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE jobs SET display_name=?, updated_at=? WHERE id=?",
                (display_name, updated_at, job_id),
            )
            await db.commit()

    async def upsert_tiles(self, job_id: str, tiles: list[TileState]) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            for tile in tiles:
                await db.execute(
                    """
                    INSERT INTO tiles (job_id, row, col, seq, status, tile_path, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_id, row, col) DO UPDATE SET
                        status=excluded.status,
                        tile_path=excluded.tile_path,
                        error=excluded.error
                    """,
                    (
                        job_id,
                        tile.row,
                        tile.col,
                        tile.seq,
                        tile.status.value,
                        tile.tile_path,
                        tile.error,
                    ),
                )
            await db.commit()

    async def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        outputs: dict | None = None,
        error: str | None = None,
        updated_at: str = "",
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            if outputs is not None:
                await db.execute(
                    "UPDATE jobs SET status=?, outputs_json=?, error=?, updated_at=? WHERE id=?",
                    (status.value, json.dumps(outputs), error, updated_at, job_id),
                )
            else:
                await db.execute(
                    "UPDATE jobs SET status=?, error=?, updated_at=? WHERE id=?",
                    (status.value, error, updated_at, job_id),
                )
            await db.commit()

    async def get_job(self, job_id: str) -> dict | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_tiles(self, job_id: str) -> list[TileState]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT row, col, seq, status, tile_path, error FROM tiles WHERE job_id=? ORDER BY seq",
                (job_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            TileState(
                row=row["row"],
                col=row["col"],
                seq=row["seq"],
                status=TileStatus(row["status"]),
                tile_path=row["tile_path"],
                error=row["error"],
            )
            for row in rows
        ]

    async def list_jobs(self, limit: int = 20) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, status, prompt, display_name, created_at, updated_at FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [dict(row) for row in rows]
