from typing import Dict, List, Optional

from unai.runtime.graph import Behavior, Capability, CapabilityGraph

class CapabilityResolver:
    """Динамический резолвер возможностей: API → Behavior → Capability."""
    
    def __init__(self, graph: CapabilityGraph):
        self._graph = graph

    def behaviors_for_methods(self, methods: List[str]) -> List[Behavior]:
        """Какие Behavior обеспечиваются доступными методами."""
        available = set(methods)
        result = []
        for b in self._graph.behaviors.values():
            if all(m in available for m in b.api_methods):
                result.append(b)
        return result

    def capabilities_for_behavior(self, behaviors: List[str]) -> List[Capability]:
        """Какие Capability достижимы при данных Behavior."""
        available = set(behaviors)
        result = []
        for c in self._graph.capabilities.values():
            if all(r in available for r in c.requires):
                result.append(c)
        return result

    def resolve_for_methods(self, methods: List[str]) -> Dict[str, List[str]]:
        """Полный проход: методы → Behavior → Capability."""
        behaviors = self.behaviors_for_methods(methods)
        caps = self.capabilities_for_behavior([b.name for b in behaviors])
        return {
            "behaviors": [b.name for b in behaviors],
            "capabilities": [c.name for c in caps],
        }
