# ADR-0003: Workspace Packaging, Storage, and Isolation

> Status: **Accepted** (2026-08-03).  
> Decision: Separate **Workspace Repository**, **Workspace Package**, and **Installed Instance**. Installed workspaces live in `~/.unai/workspaces/`, and their data/state lives separately in `~/.unai/data/`. `src/unai/workspaces` is deprecated for non-builtin workspaces.

---

## 1. Концепция трех сущностей

1. **Workspace Repository** (Git-репозиторий разработчика)  
   Пример: `wsrepos/unai-example-workspace/` или GitHub `kasper-studios/unai-discord-workspace`. Содержит README, LICENSE, CI и внутреннюю папку `workspace/`.

2. **Workspace Package** (Пакет внутри репозитория)  
   Папка `workspace/` внутри репозитория. Содержит:
   - `manifest.toml` (или `manifest.json`) — id, name, version, entry, author;
   - `run.py` — lifecycle-хендлеры (`install`, `register`, `start`, `stop`, `uninstall`);
   - `workspace.py` — доменная логика класса;
   - `requirements.txt` — зависимости.

3. **Installed Workspace & Data** (Установленный у пользователя экземпляр)  
   - Код: `~/.unai/workspaces/<id>/` (или `.unai/workspaces/<id>/` локального окружения);
   - Данные/состояние: `~/.unai/data/<id>/` (настройки, БД, кэш, логи).  
   *Обновление кода воркспейса никогда не затирает пользовательские данные.*

---

## 2. Структура пакета (`workspace/`)

```text
unai-example-workspace/          # Git-репозиторий
├── workspace/                   # Пакет для копирования ядра
│   ├── manifest.toml            # Метаданные воркспейса
│   ├── run.py                   # Lifecycle-точки входа
│   ├── workspace.py             # Реализация воркспейса
│   └── requirements.txt         # Зависимости
├── README.md
├── LICENSE
└── pyproject.toml
```

### `manifest.toml`
```toml
id = "example"
name = "Example Workspace"
version = "1.0.0"
entry = "run.py"
api = 1
author = "kasper studios"
description = "Template and example workspace"
default_enabled = false
```

### `run.py` Lifecycle Contract
```python
def install(ctx):
    """Вызывается клишкой при установке пакета (pip install -r requirements.txt и т.д.)"""
    pass

def register(kernel):
    """Вызывается ядром при загрузке: создает объект воркспейса и регистрирует манифест в микроядре"""
    pass

def start(ctx):
    """Вызывается при старте рантайма (если enabled)"""
    pass

def stop(ctx):
    """Вызывается при остановке рантайма"""
    pass

def uninstall(ctx):
    """Зачистка при удалении воркспейса"""
    pass
```

---

## 3. Процесс установки (`unai workspace install <path_or_git>`)

1. CLI клонирует/копирует `repo/workspace/` в `~/.unai/workspaces/<id>/`.
2. Вызывает `run.py:install(ctx)`.
3. Создает папку данных `~/.unai/data/<id>/`.
4. Воркспейс появляется в `unai workspace ls`.
