"""Интеграционный тест Workspace SDK НА ПРАКТИКЕ через example-воркспейс.

Пример воркспейса теперь — отдельный SDK-пакет (wsrepos/unai-example-workspace):
инструменты регистрируются ДЕКОРАТОРАМИ `@tool`, манифест несёт только метаданные.
Здесь тот же класс построен через SDK и проверяется полный сценарий:
  @tool-сборка -> manifest -> регистрация в ядре -> эмит уведомления в сервис.
"""
import asyncio

import pytest

from unai.bus.memory import InMemoryBus, InMemoryDiscovery
from unai.kernel.kernel import Microkernel
from unai.runtime.graph import Behavior, Capability, CapabilityGraph
from unai.sdk import Workspace, tool
from unai.services.notifications import NotificationService


class ExampleWorkspace(Workspace):
    """Зеркало wsrepos example-воркспейса: инструменты через `@tool`."""

    @tool(
        "example.echo",
        description="Echo a value back to the caller",
        arguments={"value": {"type": "string", "description": "The value to echo"}},
    )
    async def echo(self, value: str) -> str:
        return value

    @tool(
        "example.add",
        description="Add two numbers together",
        arguments={
            "a": {"type": "number", "description": "First operand"},
            "b": {"type": "number", "description": "Second operand"},
        },
    )
    async def add(self, a: float, b: float) -> float:
        return a + b

    @tool("example.status", description="Get the current workspace status")
    async def status(self) -> str:
        return f"ExampleWorkspace ready (runtime_id={self.runtime_id})"

    def features(self) -> dict:
        return {"notifications": True, "settings": True}


def _build_graph() -> CapabilityGraph:
    g = CapabilityGraph()
    g.add_behavior(Behavior(name="echo", description="Возвращает входные данные",
                            api_methods=["example.echo"]))
    g.add_capability(Capability(name="reflect", description="Echo-отражение",
                                requires=["echo"]))
    return g


@pytest.mark.asyncio
async def test_tools_collected_via_decorator():
    """@tool-декораторы (а не манифест) собирают инструменты воркспейса."""
    ws = ExampleWorkspace("example-1")
    assert set(ws.methods) == {"example.echo", "example.add", "example.status"}
    assert set(ws.manifest.methods) == set(ws.methods)
    # tools ключуются по имени МЕТОДА, полное имя — в ToolSpec.name
    assert set(ws.tools) == {"echo", "add", "status"}
    assert {t.name for t in ws.tools.values()} == set(ws.methods)


@pytest.mark.asyncio
async def test_tool_invoke_async_and_sync():
    """ToolSpec.invoke исполняет async-методы и возвращает результат (asyncio-safe)."""
    ws = ExampleWorkspace("example-2")
    assert await ws.tools["echo"].invoke({"value": "куку"}) == "куку"
    assert await ws.tools["add"].invoke({"a": 2, "b": 3}) == 5
    status = await ws.tools["status"].invoke({})
    assert status == "ExampleWorkspace ready (runtime_id=example-2)"


@pytest.mark.asyncio
async def test_workspace_registered_and_capabilities_resolve():
    """SDK-воркспейс регистрируется в ядре, capabilities вычисляются из графа."""
    bus, discovery = InMemoryBus(), InMemoryDiscovery()
    graph = _build_graph()
    kernel = Microkernel(bus, discovery, graph)
    ws = ExampleWorkspace("example-1", bus)

    await kernel.register_runtime(ws.manifest)

    active = await kernel.list_active_workspaces()
    assert any(w["id"] == "example-1" for w in active)
    reg = kernel._manifest_registry["example-1"]
    assert reg["features"] == {"notifications": True, "settings": True}
    assert reg["capabilities"] == ["reflect"]


@pytest.mark.asyncio
async def test_workspace_default_enabled_false():
    """Пример воркспейса — демо: по умолчанию НЕ стартует автоматически."""
    ws = ExampleWorkspace("example-1")
    assert ws.manifest.default_enabled is False


@pytest.mark.asyncio
async def test_emit_flows_to_notification_service():
    """ws.emit(topic) публикует событие в шину -> Notification Service ловит его."""
    bus, discovery = InMemoryBus(), InMemoryDiscovery()
    kernel = Microkernel(bus, discovery, _build_graph())
    ws = ExampleWorkspace("example-3", bus)
    nvcs = NotificationService(bus)
    await nvcs.start()  # подписываемся на workspace.notification

    await ws.emit("workspace.notification", {
        "workspace": "example-3",
        "title": "пингуй Дирома",
        "priority": 2,
    })
    await asyncio.sleep(0.01)

    got = await nvcs.check_notify()
    assert any(
        n["workspace"] == "example-3" and n["title"] == "пингуй Дирома"
        for n in got
    )