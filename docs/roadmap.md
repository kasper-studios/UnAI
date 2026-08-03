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
- [ ] Status Service на `event: workspace.status.changed` (обновляет статус Дирома в Discord) — после CLI/интеграции.
- [ ] Логирование и метрики как ещё два подписчика на ту же шину.

## Phase 3 — Rust CLI (`unai`) — `ADR-0001` ##
Цель: единый управляющий бинарник над рантаймом.
- [ ] Бутстрап-вариант до сборки: `uvx unai …` / `python -m unai install`.
- [ ] `clap`: `install`, `doctor`, `update`, `self-update`, `repair`, `backup/restore`, `version`, `workspace (add|remove|list|update all)`, `extension status`.
- [ ] Детектор MCP-клиентов (Claude Code, Codex, Cursor, VS Code) + авто-прописка конфигов.
- [ ] `unai install` — сам ставит venv, зависимости, регистрирует Runtime.
- [ ] `unai doctor` / `unai repair` — диагностика и починка окружения.

## Phase 4 — Workspace SDK + Browser (KasperBridge)
- [ ] Workspace SDK: контракт, чей манифест + фичи + `emit`-подписка.
- [ ] Web Workspace (KasperBridge / Tampermonkey): `dom.query`, `dom.click`, `dom.type`, `dom.wait`, MutationObserver, смена URL.
- [ ] Firefox (основной) и Chrome (песочница, аккаунт «Диром/Hermes»); расширение рапортует, из какого браузера какает.

## Phase 5 — Marketplace Workspaces (Discord → Telegram → …)
- [ ] Браузер — built-in воркспейс ядра по умолчанию (`ADR-0002`).
- [ ] Пакет **Discord Workspace (Диром)**: нативный клиент вместо DOM-эмуляции — `discord.*` methods, `notifications`/`background`/`status`. Ставится `unai workspace install discord`.
- [ ] Пакет **Telegram** как маркетплейс-воркспейс.
- [ ] Токен-экономный контракт тулов: краткое описание + ссылка на `docs/tools/<tool>.md` (`ADR-0002 §4`).
- [ ] Каталог/поиск по маркетплейсу (`unai workspace search`).

## Phase 6 — Distributed Nodes
- [ ] Планшет (Termux / Python Runtime) как удалённый узел.
- [ ] VPS (Docker / Long-lived Runtime) как облачный узел.
- [ ] Выбор узла по латентности/возможностям, failover, UNAVAILABLE.