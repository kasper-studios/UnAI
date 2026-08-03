from abc import ABC, abstractmethod
from typing import Callable, Awaitable, List, Optional

from unai.common.protocol import Message, RuntimeManifest

Handler = Callable[[Message], Awaitable[None]]


class SystemBus(ABC):
    """Системная шина: вызовы (call) + события (emit/on) + подписки."""

    @abstractmethod
    async def publish(self, message: Message) -> None:
        """Отправить сообщение в шину (call / конкретное сообщение)."""
        ...

    @abstractmethod
    async def emit(self, topic: str, payload: Optional[dict] = None,
                   source: str = "system") -> Message:
        """Опубликовать СЛУЧАЙНОЕ событие на топик (event-модель)."""
        ...

    @abstractmethod
    async def subscribe(self, topic: str, handler: Handler) -> str:
        """Подписаться на топик. Возвращает ID подписки."""
        ...

    @abstractmethod
    async def on(self, topic: str, handler: Handler) -> str:
        """Подписка на событие топика. Синоним subscribe для event-семантики."""
        ...

    @abstractmethod
    async def unsubscribe(self, subscription_id: str) -> None:
        """Отменить подписку по ID."""
        ...


class DiscoveryService(ABC):
    """Сервис обнаружения нод и рантаймов."""

    @abstractmethod
    async def announce(self, manifest: RuntimeManifest) -> None:
        """Анонсировать рантайм в систему."""
        ...

    @abstractmethod
    async def get_active_runtimes(self) -> List[RuntimeManifest]:
        """Получить список всех живых рантаймов."""
        ...