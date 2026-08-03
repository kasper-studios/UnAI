import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union

class MessageType(Enum):
    CALL = "call"         # Запрос метода (API Call)
    RESPONSE = "response" # Результат вызова
    EVENT = "event"       # Событие (Broadcast)
    DISCOVERY = "discovery" # Анонс рантайма

@dataclass(frozen=True)
class Message:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: MessageType = MessageType.CALL
    source: str = "unknown"      # ID отправителя (Node/Runtime)
    destination: str = "*"       # ID получателя или "*" для широковещания
    method: Optional[str] = None # Название метода (напр. "web.dom.click")
    payload: Dict[str, Any] = field(default_factory=dict)
    correlation_id: Optional[str] = None # Для связки Response с Call
    ts: float = field(default_factory=time.time) # Время создания сообщения

@dataclass(frozen=True)
class RuntimeManifest:
    """Описание того, что умеет конкретный рантайм/воркспейс (с опциональными фичами)."""
    runtime_id: str
    node_id: str
    methods: List[str] # Список доступных API методов
    metadata: Dict[str, Any] = field(default_factory=dict)
    features: Dict[str, bool] = field(default_factory=dict) # Опциональные фичи воркспейса (notifications, background, persistent, settings)

# Alias for backward compatibility and semantic clarity in workspace context
WorkspaceManifest = RuntimeManifest
