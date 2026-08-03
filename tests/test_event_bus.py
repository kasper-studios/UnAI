import asyncio

import pytest

from unai.bus.memory import InMemoryBus
from unai.common.protocol import Message, MessageType
from unai.services.notifications import (
    NotificationService,
    EVENT_NOTIFICATION,
    EVENT_STATUS,
)


@pytest.mark.asyncio
async def test_bus_emit_on_subscription():
    bus = InMemoryBus()
    got = []

    async def h(msg: Message):
        got.append(msg)

    sub = await bus.on("workspace.notification", h)
    event = await bus.emit("workspace.notification", {"title": "Новое сообщение"})
    assert event.type is MessageType.EVENT
    assert len(got) == 1
    assert got[0].payload["title"] == "Новое сообщение"


@pytest.mark.asyncio
async def test_bus_unsubscribe_works():
    bus = InMemoryBus()
    got = []

    async def h(msg: Message):
        got.append(msg)

    sub_id = await bus.subscribe("topic.x", h)
    await bus.emit("topic.x", {"n": 1})
    assert len(got) == 1

    await bus.unsubscribe(sub_id)
    await bus.emit("topic.x", {"n": 2})
    assert len(got) == 1, "после unsubscribe подписчик не должен получать события"


@pytest.mark.asyncio
async def test_wildcard_receives_event_once():
    bus = InMemoryBus()
    got = []

    async def h(msg: Message):
        got.append(msg)

    # wildcard и конкретный топик с одним хендлером => дедуп
    await bus.subscribe("*", h)
    await bus.subscribe("topic.y", h)
    await bus.emit("topic.y", {"n": 1})
    assert len(got) == 1


@pytest.mark.asyncio
async def test_notification_service_check():
    bus = InMemoryBus()
    svc = NotificationService(bus)
    await svc.start()

    await bus.emit(EVENT_NOTIFICATION, {
        "workspace": "discord",
        "title": "Пинг в #dev",
        "priority": 1,
    })
    await bus.emit(EVENT_NOTIFICATION, {
        "workspace": "telegram",
        "title": "Сообщение",
    })

    # небольшая пауза на доставку событий
    await asyncio.sleep(0)

    all_n = await svc.check_notify()
    assert len(all_n) == 2
    assert all_n[0]["title"] == "Пинг в #dev"

    # теперь пусто
    assert await svc.check_notify() == []


@pytest.mark.asyncio
async def test_notification_filter_by_workspace():
    bus = InMemoryBus()
    svc = NotificationService(bus)
    await svc.start()

    await bus.emit(EVENT_NOTIFICATION, {"workspace": "discord", "title": "A"})
    await bus.emit(EVENT_NOTIFICATION, {"workspace": "tg", "title": "B"})
    await asyncio.sleep(0)

    only_discord = await svc.check_notify(workspace="discord")
    assert [n["title"] for n in only_discord] == ["A"]

    # оставшиеся: только tg
    rest = await svc.check_notify()
    assert [n["title"] for n in rest] == ["B"]