# ADR-0001: CLI as an independent infrastructure binary (currently Rust)

> Status: **Accepted** (2026-08-02). Decision: the **CLI is a separate infrastructure binary,
> decoupled from the Runtime.** Its implementation language never affects the Runtime — the two
> contract through a stable external interface, not internal code. **Rust is the current
> implementation**, not a permanent commitment. Core microkernel lands first (see `roadmap.md`).

## 1. Что это (What it is)
UnAI ships a single native CLI — `unai` — as the universal entry point to the whole ecosystem. It is a **thin infrastructure command**, not part of the runtime itself:

```text
UnAI
│
├── src/unai (Python runtime + workspace SDK)
│
(unai-cli → Rust)
├── unai-cli  — install, update, doctor, workspaces, extension, self-manage
```

The CLI owns the *meta* concerns; the Python package owns the *runtime* concerns:

| Layer | Language | Decouples via | Lives for |
| :--- | :--- | :--- | :--- |
| `unai-cli` | **Rust** | external CLI↔runtime interface | install, doctor, update, workspace mgmt, MCP client config, diagnostics |
| `unai` runtime | Python | external CLI↔runtime interface | System Bus, workspaces, capability resolution, protocol |
| Workspaces | Python | their own APIs onto the bus | Browser (KasperBridge), Discord (Dirom), Telegram, Vault… |

> **Non-negotiable boundary:** The Runtime is language-agnostic w.r.t. the CLI. Rust was chosen
> for the CLI for *its* ergonomics (single binary, instant start, rich TUI crates) — it never
> constrains the runtime's own implementation. A future CLI rewrite (Zig, Go, …) would not touch
> the runtime.

## Why Rust (current implementation)

Rust is the **current** CLI implementation because:

- single native binary — user downloads `unai`, done;
- instant startup — `unai doctor` / `unai workspace list` feel native, no cold Python start;
- excellent CLI ecosystem — `clap`, `indicatif`, `dialoguer`, `comfy-table`, `ratatui`;
- zero dependency on the very Python env it must create and repair (no chicken-and-egg: you can't run a Python CLI to fix a broken Python env);
- easy distribution.

This is a distribution/ergonomics choice, not a performance requirement and not a permanent commitment.

## 2. Почему существует (Why it exists)
1. **One binary, zero setup.** `unai install` itself checks for Python, creates the venv, installs deps, detects MCP clients (Claude Code, Codex, Cursor, VS Code) and writes each client's config — the user never opens a JSON by hand.
2. **Instant startup.** A frequently-invoked command tool (`unai doctor`, `unai workspace list`) must feel native, not like a cold-start Python script.
3. **A stable, universal entry point** that scales as the ecosystem grows:

```bash
unai install                    # install everything (env detect + MCP config)
unai doctor                     # environment / clients / workspaces / extension checks
unai update                     # update the runtime
unai self-update                # update the CLI itself
unai repair                     # rebuild a broken venv / recreate missing runtime state
unai backup  [workspace.json]  # export installed workspaces, settings, versions
unai restore workspace.json     # re-import a backup
unai version                    # show CLI / Runtime / Protocol / Workspace versions
unai workspaces                 # list
unai workspace add github       # / remove / list / update all
unai extension status           # per-browser extension connection state
```

4. **Content feel without noise.** Output is clean and scriptable; interactive panels (progress, tables, prompts) only when a human is at a TTY.

## 3. Что НЕ входит (What is NOT included)
- **Not the runtime.** The CLI never runs the System Bus or hosts workspaces — it orchestrates/installs/configures them.
- **Not a replacement for Python.** Rust is chosen only for the CLI; the runtime and workspaces stay in Python (their integration surface: Discord bot, Kdenlive, MCP ecosystem).
- **Language choice never constrains the Runtime.** The CLI ↔ runtime contract is external and language-independent.
| **Not a mandatory TUI.** A full TUI (ratatui) is an optional later layer on the same Rust crate; the CLI stays scriptable.

## 5. Session & auth commands (ADR-0004)
- `unai workspace reset-session <ws_id>` — принудительный сброс сессии: удаляет
  `~/.unai/data/<id>/session.json`, состояние → `none`, `login`-тулза воркспейса
  снова доступна агенту. Доступно вне зависимости от текущего state.
- `unai workspace ls` показывает статус сессии (`none` / `valid` / `invalid`)
  — не для авто-действий, а как индикатор для юзера.

## 4. Открытые вопросы (Open Questions)
1. ~~Separate repo vs alongside `src/unai`?~~ → **Решение: моно-репо**, `unai-cli/` рядом с `src/` (2026-08-03). Упрощает бутстрип (`CARGO_MANIFEST_DIR ·/.` = корень, прямой доступ к `pyproject.toml` и `src/unai`), не мешая независимой дистрибуции бинарника.
2. How does the CLI provision a *workspace*'s own runtime deps for its venv — a workspace manifest drop-in, or per-workspace pyproject the CLI runs?
3. Bootstrap before the Rust binary is built: `uvx unai …` / `python -m unai install`.
4. Do we need an explicit `unai mcp` schema to declare an MCP server, or is it implicitly a workspace-level feature?

---

## Recommended Rust crates (shortlist)
- `clap` — arg parsing + auto `--help`
- `indicatif` — progress bars
- `dialoguer` — interactive prompts (install wizard, workspace select)
- `owo-colors` / `colored` — colored output
- `comfy-table` — workspace/tar tables
- `ratatui` — optional full TUI later