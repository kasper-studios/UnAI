"""ExampleWorkspace — минимальный пример воркспейса для проверки ядра на практике.

Сценарии, которые он демонстрирует:
1. Регистрация манифеста (RuntimeManifest) + features через Microkernel.register_runtime.
2. Подписка на шину и диспатч вызовов (CALL) по методам.
3. Эмит уведомлений (EVENT) в Notification Service через шину.
4. Ответы (RESPONSE) на вызовы.
5. **Декларативные настройки** (`settings` = SettingsSchema в манифесте):
   CLI читает схему, строит UI, вызывает `get_settings` / `set_settings`;
   воркспейс САМ хранит значения (здесь — в dict; в реальном — JSON/SQLite/Vault).

Это НЕ полный воркспейс-контракт, а самый маленький рабочий пример для тестов ядра.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, Optional

from unai.bus.interfaces import SystemBus
from unai.common.protocol import (
    Message,
    MessageType,
    RuntimeManifest,
    WorkspaceManifest,
    SettingsSchema,
    SettingItem,
)

# Топики
TOPIC_CALLS = "*"                    # диспатч любых CALL-ов, адресованных этому воркспейсу
TOPIC_RESPONSES = "example.responses"   # где воркспейс публикует ответы

#: Схема настроек — декларативная, CLI строит UI по ней, не зная воркспейс.
EXAMPLE_SETTINGS_SCHEMA = SettingsSchema(
    title="Example Settings",
    description="Пример декларативных настроек воркспейса.",
    items={
        "mode": SettingItem(
            type="choice",
            title="Mode",
            description="Режим работы воркспейса",
            choices=["echo", "silent"],
            default="echo",
        ),
        "label": SettingItem(
            type="text",
            title="Label",
            description="Подпись воркспейса (кастомный ввод)",
            default="Dirom",
        ),
        "greet": SettingItem(
            type="action",
            title="Say hello",
            description="Вызвать метод example.greet (проверка action)",
            action_method="example.greet",
        ),
    },
)


class ExampleWorkspace:
    """Минимальный воркспейс: echo-методы + эмит уведомлений + настройки."""

    def __init__(self, runtime_id: str, bus: SystemBus):
        self.runtime_id = runtime_id
        self.bus = bus
        self.manifest = WorkspaceManifest(
            runtime_id=runtime_id,
            node_id="node-1",
            methods=["example.echo", "example.greet"],
            metadata={"name": "Example Workspace", "kind": "example"},
            # Опциональные фичи, которые ядро запомнит при регистрации.
            features={"notifications": True, "settings": True},
            # Декларативная СХЕМА настроек (не значения!)
            settings=EXAMPLE_SETTINGS_SCHEMA,
            # Рекомендация автора: example — демо, не стартует сам по умолчанию.
            default_enabled=False,
        )
        self._sub_ids: list[str] = []
        self._notifications: list[dict] = []  # локальный лог уведомлений
        # Текущие значения — СОБСТВЕННОСТЬ воркспейса (здесь dict; в проде JSON/SQLite/Vault).
        self._settings: dict[str, Any] = {
            "mode": "echo",
            "label": "Dirom",
        }

    # --- Регистрация/подписки ---

    async def start(self) -> None:
        """Подписаться на вызовы и уведомления; воркспейс готов какать."""
        self._sub_ids.append(await self.bus.on(TOPIC_CALLS, self._handle_call))

    async def stop(self) -> None:
        for sub_id in self._sub_ids:
            await self.bus.unsubscribe(sub_id)
        self._sub_ids.clear()

    # --- Диспатч вызовов ---

    async def _handle_call(self, msg: Message) -> None:
        if msg.type != MessageType.CALL:
            return
        if msg.destination not in (TOPIC_CALLS, self.runtime_id, "*"):
            return  # не адресовано нам
        if msg.method == "example.echo":
            await self._respond(msg, {"echo": msg.payload.get("value")})
        elif msg.method == "example.greet":
            await self._respond(msg, {"greeting": f"Привет, {self._settings.get('label', 'Dirom')}!"})

    async def _respond(self, req: Message, data: dict) -> None:
        resp = Message(
            type=MessageType.RESPONSE,
            source=self.runtime_id,
            destination=TOPIC_RESPONSES,
            method=req.method,
            correlation_id=req.id,
            payload=data,
        )
        await self.bus.publish(resp)

    # --- Настройки (Settings API) ---

    async def get_settings(self) -> dict:
        """Вернуть текущие значения настроек (хранит сам воркспейс)."""
        return dict(self._settings)

    async def set_settings(self, values: dict) -> dict:
        """Применить значения, сохранив их у себя.

        CLI вызывает этот метод ПОСЛЕ того, как собрал ответы по схеме.
        Воркспейс сам решает, куда писать: dict / JSON / SQLite / Vault / облако.
        """
        self._settings.update(values)
        return dict(self._settings)

    # --- Уведомления (эмит в Notification Service) ---

    async def emit_notification(self, title: str, priority: int = 0) -> Message:
        """Сгенерировать уведомление в шину (NOTIFICATION) с фичей 'notifications'."""
        event = await self.bus.emit(
            "workspace.notification",
            payload={"workspace": self.runtime_id, "title": title, "priority": priority},
            source=self.runtime_id,
        )
        self._notifications.append(
            {"workspace": self.runtime_id, "title": title, "priority": priority}
        )
        return event
