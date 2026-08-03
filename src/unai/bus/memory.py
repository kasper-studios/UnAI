import asyncio
from collections import defaultdict
from typing import Awaitable, Callable, Dict, List, Optional, Set

from unai.common.protocol import Message, MessageType, RuntimeManifest
from unai.bus.interfaces import SystemBus, DiscoveryService

Handler = Callable[[Message], Awaitable[None]]


class InMemoryBus(SystemBus):
    """Событийная системная шина (in-memory, для разработки/прототипа).

    Поддерживает:
    - publish / subscribe по топикам, wildcard "*";
    - emit (событие) / on (подписка на событие) — публикация событий на топик;
    - работающий unsubscribe (реестр подписчиков по subscription_id).
    """

    def __init__(self):
        self._subs_by_topic: Dict[str, Set[str]] = defaultdict(set)
        self._handlers: Dict[str, Handler] = {}
        self._next_sub_id = 0

    def _route_to(self, message: Message) -> List[Handler]:
            """Собрать уникальные хендлеры для топика (вкл. wildcard)."""
            unique: List[Handler] = []
            seen: Set[int] = set()
            ids: Set[str] = set()
            ids |= self._subs_by_topic.get(message.destination, set())
            ids |= self._subs_by_topic.get("*", set())
            for sid in ids:
                h = self._handlers.get(sid)
                if h is None:
                    continue
                key = id(h)
                if key not in seen:
                    seen.add(key)
                    unique.append(h)
            return unique

    async def publish(self, message: Message) -> None:
        """Доставить сообщение всем подписчикам топика (wildcard "*" тоже)."""
        handlers = self._route_to(message)
        if not handlers:
            return
        await asyncio.gather(*(h(message) for h in handlers))

    async def emit(self, topic: str, payload: Optional[dict] = None,
                   source: str = "system") -> Message:
        """Опубликовать событие на топик (event-модель: workspace.notification и т.п.)."""
        event = Message(
            type=MessageType.EVENT,
            source=source,
            destination=topic,
            method=topic,
            payload=payload or {},
        )
        await self.publish(event)
        return event

    async def on(self, topic: str, handler: Handler) -> str:
        """Подписаться на событие топика. Возвращает subscription_id."""
        return await self.subscribe(topic, handler)

    async def subscribe(self, topic: str, handler: Handler) -> str:
        self._next_sub_id += 1
        sub_id = f"sub-{self._next_sub_id}"
        self._subs_by_topic[topic].add(sub_id)
        self._handlers[sub_id] = handler
        return sub_id

    async def unsubscribe(self, subscription_id: str) -> None:
        """Снять подписку: убрать из топиков и из реестра хендлеров."""
        # Убрать из всех топиков, где числится
        for topic_subs in self._subs_by_topic.values():
            topic_subs.discard(subscription_id)
        self._handlers.pop(subscription_id, None)


class InMemoryDiscovery(DiscoveryService):
    """Локальная реализация сервиса обнаружения."""

    def __init__(self):
        self._runtimes: Dict[str, RuntimeManifest] = {}

    async def announce(self, manifest: RuntimeManifest) -> None:
        self._runtimes[manifest.runtime_id] = manifest

    async def get_active_runtimes(self) -> List[RuntimeManifest]:
        return list(self._runtimes.values())