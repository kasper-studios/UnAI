from dataclasses import dataclass, field
from typing import Any, Dict, List

@dataclass(frozen=True)
class Behavior:
    """Устойчивое описание того, что умеет рантайм (слой между API и Capability)."""
    name: str
    description: str
    api_methods: List[str]  # Примеры методов, дающие это поведение

@dataclass(frozen=True)
class Capability:
    """Составная возможность, выводимая из набора Behavior."""
    name: str
    description: str
    requires: List[str]  # Список имён Behavior

@dataclass
class CapabilityGraph:
    """Граф зависимостей: Capability → Behavior → API."""
    behaviors: Dict[str, Behavior] = field(default_factory=dict)
    capabilities: Dict[str, Capability] = field(default_factory=dict)

    def add_behavior(self, b: Behavior) -> None:
        self.behaviors[b.name] = b

    def add_capability(self, c: Capability) -> None:
        self.capabilities[c.name] = c

    def resolve_capability(self, capability_name: str, available_methods: List[str]) -> bool:
        """Проверить, достижима ли Capability из доступных методов."""
        cap = self.capabilities.get(capability_name)
        if not cap:
            return False
        for behavior_name in cap.requires:
            behavior = self.behaviors.get(behavior_name)
            if not behavior:
                return False
            if not all(m in available_methods for m in behavior.api_methods):
                return False
        return True
