import pytest
import asyncio
from unai.kernel.kernel import Microkernel
from unai.common.protocol import RuntimeManifest
from unai.bus.memory import InMemoryBus, InMemoryDiscovery
from unai.runtime.graph import CapabilityGraph

@pytest.mark.asyncio
async def test_kernel_registers_workspace_with_features():
    bus = InMemoryBus()
    discovery = InMemoryDiscovery()
    graph = CapabilityGraph()
    kernel = Microkernel(bus, discovery, graph)

    manifest = RuntimeManifest(
        runtime_id="discord-ws",
        node_id="node-a",
        methods=["discord.chats.list"],
        metadata={"name": "Discord Workspace"},
        features={"notifications": True, "background": True}
    )

    await kernel.register_runtime(manifest)
    
    workspaces = await kernel.list_active_workspaces()
    assert len(workspaces) == 1
    assert workspaces[0]["id"] == "discord-ws"
    assert workspaces[0]["features"]["notifications"] is True
    assert "settings" not in workspaces[0]["features"] # Опциональность!
