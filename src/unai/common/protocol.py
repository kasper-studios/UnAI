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

# ---------------------------------------------------------------------------
# Settings schema (декларативное описание настроек воркспейса)
# ---------------------------------------------------------------------------

#: Типы полей схемы настроек.
#: - choice: выбор из списка (choices или динамический provider)
#: - text:   свободный ввод
#: - action: действие (не ввод — кнопка, напр. "Install Browser Bridge")
SettingItemType = Union["choice", "text", "action"]  # type: ignore


@dataclass(frozen=True)
class SettingItem:
    """Один элемент схемы настроек воркспейса.

    `type`:
        - "choice" — выбор из статического `choices` или динамического `provider`;
        - "text"   — свободный ввод (с `default` / `allow_custom`);
        - "action" — действие без значения (title + описание; CLI спросит подтверждение).
    """
    type: str  # "choice" | "text" | "action"
    title: str
    description: str = ""
    # Для choice:
    choices: Optional[List[str]] = None
    # Динамический список вариантов: {"provider": "<workspace_method>", "args": {...}}
    provider: Optional[Dict[str, Any]] = None
    allow_custom: bool = False
    default: Any = None
    # Для action:
    action_method: Optional[str] = None  # метод воркспейса, вызываемый при подтверждении
    required: bool = False


@dataclass(frozen=True)
class SettingsSchema:
    """Декларативная схема настроек воркспейса (не значения!).

    CLI читает эту схему, строит интерактивный UI и запрашивает значения
    через `workspace.get_settings()` / `workspace.set_settings()`.
    """
    title: str
    description: str = ""
    items: Dict[str, SettingItem] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "items": {
                key: {
                    "type": item.type,
                    "title": item.title,
                    "description": item.description,
                    **({"choices": item.choices} if item.choices is not None else {}),
                    **({"provider": item.provider} if item.provider is not None else {}),
                    "allow_custom": item.allow_custom,
                    "default": item.default,
                    **({"action_method": item.action_method} if item.action_method else {}),
                    "required": item.required,
                }
                for key, item in self.items.items()
            },
        }


@dataclass(frozen=True)
class RuntimeManifest:
    """Описание того, что умеет конкретный рантайм/воркспейс (с опциональными фичами).

    `settings` — это СХЕМА (SettingsSchema), а не значения. Значения живут вне
    манифеста (их хранит сам воркспейс: JSON / SQLite / Vault / облако) и
    читаются/пишутся через методы `get_settings` / `set_settings`.
    """
    runtime_id: str
    node_id: str
    methods: List[str] # Список доступных API методов
    metadata: Dict[str, Any] = field(default_factory=dict)
    features: Dict[str, bool] = field(default_factory=dict) # Опциональные фичи воркспейса (notifications, background, persistent, settings)
    settings: Optional[SettingsSchema] = None  # Декларативная схема настроек (не значения!)
    default_enabled: bool = False  # Рекомендация автора воркспейса (НЕ текущее состояние!).

# Alias for backward compatibility and semantic clarity in workspace context
WorkspaceManifest = RuntimeManifest
