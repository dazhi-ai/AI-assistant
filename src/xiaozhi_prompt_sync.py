"""Periodically sync the role system_prompt from xiaozhi MySQL."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class XiaozhiPromptSync:
    """Read system_prompt from xiaozhi-esp32-server MySQL and refresh on a timer."""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        db: str,
        agent_id: str,
        refresh_seconds: int = 600,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._db = db
        self._agent_id = agent_id
        self._refresh_seconds = max(refresh_seconds, 30)
        self._prompt: str = ""
        self._lock = threading.Lock()
        self._task: Optional[asyncio.Task] = None

    @property
    def enabled(self) -> bool:
        return bool(self._agent_id and self._password)

    @property
    def prompt(self) -> str:
        with self._lock:
            return self._prompt

    def _fetch_prompt_from_db(self) -> str:
        """Blocking call: connect to MySQL and read system_prompt for the configured agent."""
        import pymysql

        conn = pymysql.connect(
            host=self._host,
            port=self._port,
            user=self._user,
            password=self._password,
            database=self._db,
            connect_timeout=10,
            read_timeout=10,
            charset="utf8mb4",
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT system_prompt FROM ai_agent WHERE id = %s LIMIT 1",
                    (self._agent_id,),
                )
                row = cur.fetchone()
                if row and row[0]:
                    return str(row[0]).strip()
                return ""
        finally:
            conn.close()

    async def _do_refresh(self) -> None:
        """Run the blocking DB query in an executor to avoid blocking the event loop."""
        loop = asyncio.get_running_loop()
        try:
            new_prompt = await loop.run_in_executor(None, self._fetch_prompt_from_db)
            if new_prompt:
                with self._lock:
                    self._prompt = new_prompt
                logger.info(
                    "Xiaozhi prompt refreshed (%d chars, agent=%s)",
                    len(new_prompt),
                    self._agent_id[:8],
                )
            else:
                logger.warning("Xiaozhi prompt query returned empty for agent=%s", self._agent_id)
        except Exception:
            logger.exception("Failed to refresh xiaozhi prompt from MySQL")

    async def start(self) -> None:
        """Load prompt once, then schedule periodic refresh."""
        if not self.enabled:
            logger.info("XiaozhiPromptSync disabled (missing agent_id or password)")
            return
        await self._do_refresh()
        self._task = asyncio.create_task(self._refresh_loop())

    async def _refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(self._refresh_seconds)
            await self._do_refresh()

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
