"""Session migration helpers."""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from mebot.session.manager import SessionManager
from mebot.session.redis_manager import RedisSessionManager


def migrate_disk_to_redis(sessions_dir: Path, redis_manager: RedisSessionManager) -> int:
    """Migrate all disk JSONL sessions into Redis storage."""
    sessions_dir = sessions_dir.expanduser().resolve()
    if not sessions_dir.exists():
        return 0

    disk_manager = SessionManager(sessions_dir.parent)
    migrated = 0
    for jsonl_path in sessions_dir.glob("*.jsonl"):
        key = _read_session_key(jsonl_path)
        if not key:
            continue
        session = disk_manager._load(key)  # noqa: SLF001 - migration utility
        if not session:
            continue
        redis_manager.save(session)
        migrated += 1
    logger.info("Migrated {} sessions from disk to Redis", migrated)
    return migrated


def _read_session_key(path: Path) -> str | None:
    try:
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
        data = json.loads(first_line)
        if isinstance(data, dict) and data.get("_type") == "metadata":
            key = data.get("key")
            if isinstance(key, str) and key:
                return key
    except Exception:
        return None
    return None
