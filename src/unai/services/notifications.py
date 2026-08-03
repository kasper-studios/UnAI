from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from unai.bus.interfaces import SystemBus

# Топики событий, на которые подписывается Notification Service
EVENT_NOTIFICATION = "workspace.notification"
EVENT_STATUS = "workspace.status.changed"


class NotificationService:
    """Notification Center — тонкий слой поверх System Bus.

    Не опрашивает воркспейсы. Просто подписан на событие `workspace.notification`
    и копит записи; `check_notify` отдаёт накопленное (все — или по workspace).
    Логика — целиком на шине, никаких пуллов.
    """

    def __init__(self, bus: SystemBus, max_history: int = 200):
        self._bus = bus
        self._max_history = max_history
        self._entries: List[Dict[str, Any]] = []
        self._sub_id: Optional[str] = None

    async def _handle(self, msg) -> None:
        payload = msg.payload or {}
        entry = {
            "workspace": payload.get("workspace"),
            "title": payload.get("title"),
            "priority": payload.get("priority", 0),
            "payload": payload,
            "ts": None,
        }
        self._entries.append(entry)
        if len(self._entries) > self._max_history:
            self._entries = self._entries[-self._max_history:]

    async def start(self) -> str:
        """Подписаться на события уведомлений на шине."""
        self._sub_id = await self._bus.on(EVENT_NOTIFICATION, self._handle)
        return self._sub_id

    async def stop(self) -> None:
        if self._sub_id:
            await self._bus.unsubscribe(self._sub_id)
            self._sub_id = None

    async def check_notify(self, workspace: Optional[str] = None,
                           clear: bool = True) -> List[Dict[str, Any]]:
        """Вернуть уведомления (все, либо фильтр workspace). По умолчанию очищает."""
        if workspace is None:
            result = list(self._entries)
            if clear:
                self._entries.clear()
            return result

        result = [e for e in self._entries if e["workspace"] == workspace]
        if clear:
            self._entries = [e for e in self._entries if e["workspace"] != workspace]
        return result