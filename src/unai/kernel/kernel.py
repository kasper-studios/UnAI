from unai.bus.interfaces import SystemBus, DiscoveryService
from unai.common.protocol import Message, MessageType, RuntimeManifest
from unai.kernel.resolver import CapabilityResolver
from unai.runtime.graph import CapabilityGraph
from typing import List, Dict, Any

class Microkernel:
    """Минимальное ядро: Node Management, Bus Routing, Runtime Lifecycle, Capability Resolution."""
    
    def __init__(self, bus: SystemBus, discovery: DiscoveryService, graph: CapabilityGraph):
        self._bus = bus
        self._discovery = discovery
        self._resolver = CapabilityResolver(graph)
        self._manifest_registry: dict = {}

    async def register_runtime(self, manifest) -> None:
        """Зарегистрировать рантайм/воркспейс: анонс + вычисление возможностей."""
        await self._discovery.announce(manifest)
        resolution = self._resolver.resolve_for_methods(manifest.methods)
        
        # Сохраняем все, включая опциональные фичи (features)
        self._manifest_registry[manifest.runtime_id] = {
            "manifest": manifest,
            "capabilities": resolution["capabilities"],
            "behaviors": resolution["behaviors"],
            "features": manifest.features, # Вот они!
        }

    async def call(self, method: str, payload: dict, destination: str = "*") -> Message:
        """Исполнить вызов метода через шину."""
        request = Message(
            type=MessageType.CALL,
            method=method,
            payload=payload,
            destination=destination,
        )
        await self._bus.publish(request)
        return request

    async def list_active_workspaces(self) -> List[Dict[str, Any]]:
        """List active workspaces (runtimes) with their features."""
        return [
            {
                "id": info["manifest"].runtime_id,
                "name": info["manifest"].metadata.get("name", "Unknown"),
                "features": info["features"]
            }
            for info in self._manifest_registry.values()
        ]