"""Интеграционный тест ядра НА ПРАКТИКЕ через реальный example-воркспейс.

Не отдельные юниты, а полный сценарий:
  kernel (bus+discovery+graph) <- ExampleWorkspace <- NotificationService
Проверяем регистрацию, диспатч-вызов, эмит уведомлений и ответы.
"""
import asyncio

import pytest

from unai.bus.memory import InMemoryBus, InMemoryDiscovery
from unai.common.protocol import Message, MessageType
from unai.kernel.kernel import Microkernel
from unai.runtime.graph import Behavior, Capability, CapabilityGraph
from unai.services.notifications import NotificationService
from unai.workspaces.example_ws import ExampleWorkspace


def _build_graph() -> CapabilityGraph:
    g = CapabilityGraph()
    g.add_behavior(Behavior(name="echo", description="Возвращает входные данные",
                            api_methods=["example.echo"]))
    g.add_capability(Capability(name="reflect", description="Echo-отражение", requires=["echo"]))
    return g


@pytest.mark.asyncio
async def test_workspace_registered_and_capabilities_resolve():
    bus, discovery = InMemoryBus(), InMemoryDiscovery()
    graph = _build_graph()
    kernel = Microkernel(bus, discovery, graph)
    ws = ExampleWorkspace("example-1", bus)

    await kernel.register_runtime(ws.manifest)

    # Ядро зарегистрировало воркспейс и запомнило его фичи + capabilities
    active = await kernel.list_active_workspaces()
    assert any(w["id"] == "example-1" for w in active)
    reg = kernel._manifest_registry["example-1"]
    assert reg["features"] == {"notifications": True, "settings": True}
    assert reg["capabilities"] == ["reflect"]


@pytest.mark.asyncio
async def test_echo_call_dispatched_and_response_published():
    bus, discovery = InMemoryBus(), InMemoryDiscovery()
    kernel = Microkernel(bus, discovery, _build_graph())
    ws = ExampleWorkspace("example-2", bus)
    await ws.start()

    # подписываемся на топик ответов
    responses: list[Message] = []
    async def _collect(m: Message) -> None:
        responses.append(m)
    await bus.on("example.responses", _collect)

    # CALL как сделал бы агент: публикуем echo на задиспатчивание воркспейсом
    await bus.publish(Message(type=MessageType.CALL, method="example.echo",
                              destination="*", payload={"value": "куку"}))
    await asyncio.sleep(0.01)

    assert len(responses) == 1
    assert responses[0].type == MessageType.RESPONSE
    assert responses[0].payload == {"echo": "куку"}


@pytest.mark.asyncio
async def test_notification_flows_to_service():
    bus, discovery = InMemoryBus(), InMemoryDiscovery()
    kernel = Microkernel(bus, discovery, _build_graph())
    ws = ExampleWorkspace("example-3", bus)
    nvcs = NotificationService(bus)
    await nvcs.start()  # подписываемся на workspace.notification

    await ws.emit_notification("пингуй Дирома", priority=2)
    await asyncio.sleep(0.01)

    got = await nvcs.check_notify()
    assert any(n["workspace"] == "example-3" and n["title"] == "пингуй Дирома" for n in got)