"""UnAI Workspace SDK.

Воркспейс декларирует свои инструменты ДЕКОРАТОРАМИ (код), а не манифестом.
Манифест (`manifest.toml` / `RuntimeManifest`) несёт только метаданные:
id, name, version, entry, author — и НЕ содержит списка инструментов.

Инструменты собираются через `__init_subclass__` при создании класса
воркспейса и автоматически попадают в `manifest.methods`.
"""

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from unai.bus.interfaces import SystemBus
from unai.common.protocol import Message, MessageType, RuntimeManifest


@dataclass(frozen=True)
class ToolSpec:
    """Описание одного инструмента воркспейса (создаётся декоратором `@tool`).

    `enabled_if` — необязательный предикат `Callable[[Workspace], bool]`.
    Если задан, тулза попадает в `methods`/`manifest.methods` ТОЛЬКО когда
    предикат возвращает True для данного инстанса (см. ADR-0004: login-тулза
    скрывается после успешного входа и появляется после reset/invalid).
    """

    name: str
    description: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)
    handler: Optional[Callable[..., Any]] = None
    #: bound-метод после инстанцирования воркспейса
    bound: Optional[Callable[..., Any]] = None
    #: state-зависимая видимость (ADR-0004)
    enabled_if: Optional[Callable[[Any], bool]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "arguments": self.arguments,
        }

    async def invoke(self, args: Dict[str, Any]) -> Any:
        """Вызвать инструмент с аргументами (async-обёртка)."""
        fn = self.bound or self.handler
        if fn is None:
            raise RuntimeError(f"tool '{self.name}' has no handler")
        if inspect.iscoroutinefunction(fn):
            return await fn(**args)
        return fn(**args)


def tool(
    name: str,
    description: str = "",
    arguments: Optional[Dict[str, Any]] = None,
    enabled_if: Optional[Callable[[Any], bool]] = None,
):
    """Декоратор: регистрирует метод воркспейса как инструмент.

    `enabled_if` — предикат на инстансе воркспейса; если есть и возвращает
    False, тулза скрывается из `methods`/MCP (см. ADR-0004).
    """
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn.__unai_tool__ = ToolSpec(  # type: ignore[attr-defined]
            name=name,
            description=description,
            arguments=arguments or {},
            handler=fn,
            enabled_if=enabled_if,
        )
        return fn
    return decorator


class Workspace:
    """Базовый класс воркспейса UnAI.

    Наследник:
    - объявляет методы с `@tool(...)` — они автоматически попадают в
      `self.tools` и `self.manifest.methods`;
    - передаёт `runtime_id` и `bus` в конструктор (или переопределяет `__init__`);
    - может переопределить `start()` / `stop()` для асинхронной инициализации.

    Состояние видимости тулов (`enabled_if`) вычисляется динамически:
    `methods`, `tools` и `manifest.methods` фильтруют тулзы по предикату
    при каждом обращении. Чтобы смена state подхватилась — достаточно
    пересчитать `manifest` (делается ядром при загрузке/регистрации).
    """

    #: Собирается через __init_subclass__: {method_name: ToolSpec}
    _tools: Dict[str, ToolSpec] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        tools: Dict[str, ToolSpec] = {}
        for attr_name, attr in vars(cls).items():
            spec = getattr(attr, "__unai_tool__", None)
            if isinstance(spec, ToolSpec):
                tools[attr_name] = spec
        cls._tools = tools  # type: ignore[assignment]

    def __init__(self, runtime_id: str, bus: Optional[SystemBus] = None, **kwargs: Any):
        self.runtime_id = runtime_id
        self.bus = bus
        # Привязываем дескрипторы к инстансу (bound-метод); предикат enabled_if
        # сохраняем как есть — он уже замкнут на self через замыкание при
        # определении в воркспейсе (см. ADR-0004 примеры).
        for method_name, spec in self._tools.items():
            bound = getattr(self, method_name)
            self._tools[method_name] = ToolSpec(
                name=spec.name,
                description=spec.description,
                arguments=spec.arguments,
                handler=spec.handler,
                bound=bound,
                enabled_if=spec.enabled_if,
            )

    # ------------------------------------------------------------------
    # Manifest: методы собираются из @tool-декораторов автоматически.
    # Фильтр enabled_if применяется динамически — state определяется
    # через вызов предиката с `self`.
    # ------------------------------------------------------------------
    @property
    def methods(self) -> List[str]:
        return [
            spec.name
            for spec in self._tools.values()
            if spec.enabled_if is None or spec.enabled_if(self)
        ]

    @property
    def tools(self) -> Dict[str, ToolSpec]:
        return {
            name: spec
            for name, spec in self._tools.items()
            if spec.enabled_if is None or spec.enabled_if(self)
        }

    @property
    def manifest(self) -> RuntimeManifest:
        return RuntimeManifest(
            runtime_id=self.runtime_id,
            node_id="node-1",
            methods=self.methods,
            metadata=self.metadata(),
            features=self.features(),
        )

    # ------------------------------------------------------------------
    # Хуки, которые воркспейс может переопределить
    # ------------------------------------------------------------------
    def metadata(self) -> Dict[str, Any]:
        return {"name": type(self).__name__, "kind": "workspace"}

    def features(self) -> Dict[str, bool]:
        return {}

    async def start(self) -> None:
        """Вызывается ядром при активации воркспейса (on-demand, перед первым вызовом)."""
        return None

    async def stop(self) -> None:
        """Вызывается ядром при деактивации воркспейса."""
        return None

    async def get_settings(self) -> Dict[str, Any]:
        return {}

    async def set_settings(self, values: Dict[str, Any]) -> Dict[str, Any]:
        return values

    # ------------------------------------------------------------------
    # Утилиты: удобный доступ к шине из методов воркспейса
    # ------------------------------------------------------------------
    async def emit(self, topic: str, payload: Optional[dict] = None) -> None:
        if self.bus is not None:
            await self.bus.emit(topic, payload, source=self.runtime_id)

    async def call(self, method: str, payload: Optional[dict] = None,
                   destination: str = "*") -> Message:
        if self.bus is None:
            raise RuntimeError("bus is not attached")
        msg = Message(
            type=MessageType.CALL,
            source=self.runtime_id,
            destination=destination,
            method=method,
            payload=payload or {},
        )
        await self.bus.publish(msg)
        return msg
