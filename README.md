# UnAI

> **Originally derived from *Universal Unified AI*.** The name is used as-is.

**UnAI** is a workspace-centric runtime for autonomous AI agents. Instead of treating an agent as a single process with a fixed set of tools, UnAI models execution as a set of **workspaces** — pluggable, persistent environments (Discord, Telegram, web browser, …) — each registering itself and its capabilities against a minimal microkernel over a common system bus.

The project is under active development: the microkernel, in-memory system bus and workspace registry are implemented in `src/unai/`. The rest is a living architecture spec under `docs/`.

---

## Why

Existing agent frameworks (LangGraph, CrewAI, AutoGen, OpenHands) usually assume:

* **Single-Process Monolith** — execution happens inside one host process.
* **Single-Machine Context** — all tools and environments live on one box.
* **Static Tool Integration** — hardcoded tool schemas need custom code per service.
* **Tightly Coupled Integrations** — a new platform means a new, bespoke integration module.

UnAI explores a different model:

* **Workspace-centric** — a workspace replaces browser emulation with native APIs, `emit`s events, holds its own state, settings and background tasks.
* **Runtime Discovery** — workspaces announce themselves as they come online.
* **Microkernel architecture** — the core only handles node/workspace management, System Bus routing, lifecycle, and capability resolution.
* **Event-driven** — Notification Center, Status, Metrics all just subscribe to the same bus; nothing polls.

**Existing frameworks expose tools. UnAI exposes an execution environment.**

---

## Core Idea

> **Workspaces publish APIs.**  
> **The system discovers behavior.**  
> **Capabilities emerge.**  
> **Agents consume behavior, not implementations.**

A workspace (web, Discord, Telegram, vault, python…) publishes its API — nothing else. The system discovers behaviors from those methods, derives capabilities dynamically, builds a dependency graph, and resolves agent intents to concrete workspaces. Capabilities are never declared, never hardcoded — they emerge.

---

## Design Principles

1. **Minimal Kernel** — one handles only the System Bus, workspace lifecycle and capability resolution.
2. **Workspace-centric** — the browser is just one workspace, not the platform.
3. **Optional features** — a workspace may support `notifications`, `persistent`, `background`, `settings` — or none; the kernel never requires a full interface.
4. **Capabilities are emergent properties of workspace methods** — never declared.
5. **Everything is replaceable / technology agnostic** — a Web workspace stays a Web workspace whether on Firefox, Chrome, Electron or WebView.

---

## Layout

```
├── pyproject.toml          # name = "unai"
├── docs/                   # Architecture RFC / specs
│   ├── architecture/ …     # kernel, system-bus, capabilities, behavior, runtime, workspace, planner, cluster
│   ├── adr/                # Architecture Decision Records (e.g. 0001-unai-cli)
│   ├── research/ …
└── src/unai/              # Core package
    ├── bus/               # SystemBus, discovery, in-memory implementation
    ├── kernel/            # Microkernel: register_workspace, list_active_workspaces, call
    ├── runtime/           # capability graph resolver
    └── common/            # protocol: Message, RuntimeManifest / WorkspaceManifest, features
```

> **CLI:** `unai` is planned as a Rust binary (`docs/adr/0001-unai-cli.md`) — install, doctor,
> update and workspace management as a thin infra tool over the Python runtime.

## Status

- [x] Workspace registration + manifest (with optional `features`)
- [x] Active-workspace listing
- [x] `call` method dispatch over System Bus
- [x] In-memory System Bus (publish/subscribe) + Discovery
- [ ] Event-driven Notification Center (subscribe to bus — next)
- [ ] RPC Dispatcher
- [ ] Real transports (UDS / WS / gRPC)
- [ ] Native Discord Workspace (Dirom), web browser (KasperBridge), Telegram…

---

## Non-Goals

UnAI does **NOT** aim to:

- Replace Linux / Docker / Kubernetes / browsers.
- Become another programming language.
- Own application-level business logic.

---

## License

Open architectural specification and research workspace. RFC-style docs, working prototype kernel.