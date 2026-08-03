# UnAI Workspace Marketplace

Каталог доступных воркспейсов. Каждая запись в `index.json` указывает на
отдельный git-репозиторий с пакетом воркспейса (см. `docs/adr/0003-workspace-packaging-and-storage.md`).

## Установка

```bash
unai workspace install <id>
```

CLI читает `index.json`, клонирует репозиторий в темп, копирует папку `path`
в `~/.unai/workspaces/<id>/` и вызывает lifecycle-хук `install()`.
