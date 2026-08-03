# Roadmap — UnAI

> Курс: **Рабочий порядок: 1) ядро до конца → 2) CLI → 3) воркспейсы.** Приоритет фиксирован: сперва закрываем ядро и событийную шину, потом делаем `unai`-CLI (Rust, `ADR-0001`) и её настройку, и только затем думаем о конкретных воркспейсах (маркетплейс, `ADR-0002`).

## Phase 1 — Core ✅
Цель: минимальное ядро, на котором всё стыкуется.
- [x] Пакет `unai`, воркспейс-центричный манифест (`RuntimeManifest` / `WorkspaceManifest` + опциональные `features`).
- [x] Регистрация / листинг активных воркспейсов (`list_active_workspaces`).
- [x] `call`-диспетчер методов через System Bus.
- [x] In-memory System Bus (publish/subscribe, wildcard) + in-memory Discovery.
- [x] Capability Resolver: методы → Behavior → Capability (эмерджентно, не хардкод).
- [x] **System Bus — событийная шина**: реестр подписчиков с `subscribe`/`unsubscribe` по ID, broadcast по топикам, wildcard-дедуп, event-модель (`emit` / `on`, `EVENT`-тип сообщения, ts).
- [x] **Event-moodle**: `emit` (событие) vs `call`, типовые контракты (`workspace.notification`, `workspace.status.changed`).
- [x] Тесты: `pytest` зелёный (`tests/`, вкл. `test_event_bus.py`).

## Phase 2 — Event Bus + Notification Service
Цель: ничего не поллит, всё подпишивается на шину.
- [x] System Bus как единый событийный бэкбон: `emit` / `subscribe` / `unsubscribe`.
- [x] Notification Service — тонкий слой над шиной без пуллов (`services/notifications.py`).
- [x] `event: workspace.notification` → Notification Service → `check_notify` (без опросов).
- [ ] Status Service на `event: workspace.status.changed` — обновляет статус агента в Discord.
- [ ] Логирование и метрики как ещё два подписчика на ту же шину.

## Phase 3 — Rust CLI (`unai`) — `ADR-0001` ✅
Цель: единый управляющий бинарник над рантаймом.
- [x] Моно-репо: `unai-cli/` рядом с `src/` (`ADR-0001 §4`).
- [x] `clap`: `version`, `doctor`, `install --force`, `workspace list` (реестр из `src/unai/workspaces/`).
- [x] `doctor` — проверка venv/Python/Rust + импорт рантайма.
- [x] `install` — создание venv + editable-установка рантайма.
- [ ] Бутстрап: `uvx unai …` / `python -m unai install` (часть 3).
- [ ] Расширение: `update`, `self-update`, `repair`, `backup/restore`, `extension status`.

## Phase 4 — Workspace SDK + Browser (built-in)
Цель: контракт воркспейса и единственный встроенный воркспейс.
- [ ] Workspace SDK: контракт, чей манифест + фичи + `emit`-подписка.
- [ ] Web Workspace (built-in browser): `dom.query`, `dom.click`, `dom.type`, `dom.wait`, MutationObserver, смена URL.
- [ ] Firefox (основной) и Chrome (песочница); расширение рапортует, из какого браузера какает.

## Phase 5 — Marketplace (`wsmarketplace/`)
Цель: каталог доступных воркспейсов внутри репо, CLI читает его при `install`.
- [ ] Папка `wsmarketplace/` в корне репо — каждый воркспейс отдельной директорией с манифестом (`ws.json`).
- [ ] CLI `unai workspace list` парсит `wsmarketplace/` и показывает доступные пакеты.
- [ ] CLI `unai workspace install <id>` копирует/симлинкит выбранный воркспейс в `src/unai/workspaces/` и регистрирует его в ядре.
- [ ] Marketplace не требует отдельного сервера — каталог живёт в том же репо, что и ядро.

## Phase 6 — Distributed Nodes
- [ ] Планшет (Termux / Python Runtime) как удалённый узел.
- [ ] VPS (Docker / Long-lived Runtime) как облачный узел.
- [ ] Выбор узла по латентности/возможностям, failover, UNAVAILABLE.