use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use std::path::PathBuf;

/// UnAI — a workspace-oriented runtime for autonomous AI agents.
/// The infrastructure CLI: install, doctor, update, workspace management.
#[derive(Parser)]
#[command(name = "unai", version, about)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Show CLI / runtime / protocol version info
    Version,
    /// Diagnose environment: python, venv, rust, package install
    Doctor,
    /// Install the Python runtime (creation of venv + editable package)
    Install {
        /// Recreate the venv even if it already exists
        #[arg(long)]
        force: bool,
    },
    /// Workspace management: list / add / remove
    Workspace {
        #[command(subcommand)]
        command: WorkspaceCmd,
    },
    /// Interactive settings for a workspace (reads settings schema from its manifest)
    Config {
        /// Workspace id to configure
        #[arg(value_name = "WS_ID")]
        id: String,
    },
}

#[derive(Subcommand)]
enum WorkspaceCmd {
    /// List installed / known workspaces
    List,
    /// Install a workspace from the marketplace (or local path)
    Install {
        #[arg(value_name = "WS_ID")]
        id: String,
        /// Install from a local path (repo dir or workspace/ dir) instead of marketplace
        #[arg(long)]
        path: Option<String>,
    },
    /// Uninstall a workspace (removes code + data)
    Uninstall {
        #[arg(value_name = "WS_ID")]
        id: String,
    },
    /// Update a workspace to the latest marketplace version
    Update {
        #[arg(value_name = "WS_ID")]
        id: String,
    },
    /// Enable a workspace (started by default on runtime launch)
    Enable {
        #[arg(value_name = "WS_ID")]
        id: String,
    },
    /// Disable a workspace (NOT started on launch; kept in registry)
    Disable {
        #[arg(value_name = "WS_ID")]
        id: String,
    },
    /// Start a workspace now (calls run.py:start)
    Start {
        #[arg(value_name = "WS_ID")]
        id: String,
    },
    /// Stop a workspace now (calls run.py:stop)
    Stop {
        #[arg(value_name = "WS_ID")]
        id: String,
    },
}

const VENV_DIR: &str = ".venv";
const PYPROJECT: &str = "pyproject.toml";
// Common Python executable names inside a venv, in priority order
const VENV_PY: &[&str] = &["bin/python", "Scripts/python.exe"];

/// Project root = Папка, содержащая pyproject.toml (ядро UnAI).
/// При прямом запуске бинарника CARGO_MANIFEST_DIR не задан, поэтому
/// поднимаемся от текущей директории в поисках pyproject.toml.
fn project_root() -> PathBuf {
    if let Ok(dir) = std::env::var("CARGO_MANIFEST_DIR") {
        let p = PathBuf::from(dir);
        if let Some(parent) = p.parent() {
            if parent.join(PYPROJECT).exists() {
                return parent.to_path_buf();
            }
        }
        if p.join(PYPROJECT).exists() {
            return p;
        }
    }
    // Runtime: поднимаемся от cwd (или используем cwd) до папки с pyproject.toml
    let start = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let mut cur = Some(start.as_path());
    while let Some(d) = cur {
        if d.join(PYPROJECT).exists() {
            return d.to_path_buf();
        }
        cur = d.parent();
    }
    start
}

fn venv_python(root: &PathBuf) -> Option<PathBuf> {
    for py in VENV_PY {
        let candidate = root.join(VENV_DIR).join(py);
        if candidate.exists() {
            return Some(candidate);
        }
    }
    None
}

fn run(cmd: &mut std::process::Command) -> Result<std::process::Output> {
    Ok(cmd
        .output()
        .with_context(|| format!("failed to run command: {cmd:?}"))?)
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    let root = project_root();

    match cli.command {
        Commands::Version => cmd_version(&root),
        Commands::Doctor => cmd_doctor(&root),
        Commands::Install { force } => cmd_install(&root, force),
        Commands::Workspace { command } => cmd_workspace(&root, command),
        Commands::Config { id } => cmd_config(&root, &id),
    }
}

fn cmd_version(_root: &PathBuf) -> Result<()> {
    println!("unai-cli {}", env!("CARGO_PKG_VERSION"));
    println!(
        "runtime: {}",
        pyproject_version().unwrap_or_else(|_| "unknown".into())
    );
    println!("protocol: 1.0");
    Ok(())
}

/// Extract `version = "..."` from pyproject.toml.
fn pyproject_version() -> Result<String> {
    let pyproject = std::fs::read_to_string(
        project_root().join(PYPROJECT),
    )
    .context("read pyproject.toml")?;
    for line in pyproject.lines() {
        let line = line.trim();
        if let Some(rest) = line.strip_prefix("version") {
            if let Some(start) = rest.find('"') {
                let inner = &rest[start + 1..];
                if let Some(end) = inner.find('"') {
                    return Ok(inner[..end].to_string());
                }
            }
        }
    }
    anyhow::bail!("version not found in pyproject.toml")
}

fn cmd_doctor(root: &PathBuf) -> Result<()> {
    println!("UnAI doctor");

    let py = match venv_python(root) {
        Some(p) => p,
        None => {
            println!("  ✗ venv  : NOT FOUND (run `unai install`)");
            return Ok(());
        }
    };
    println!("  ✓ venv  : {}", py.display());

    // venv python --version
    let ver = run(std::process::Command::new(&py)
        .arg("--version"))?;
    let python_ver = String::from_utf8_lossy(&ver.stdout);
    println!("  ✓ python: {}", python_ver.trim());

    // runtime import check
    let imp = run(std::process::Command::new(&py)
        .arg("-c")
        .arg("import unai; print(unai.__file__ or 'ok')"))?;
    if imp.status.success() {
        println!("  ✓ runtime import: ok");
    } else {
        println!("  ✗ runtime import: FAILED");
    }

    let rustc = run(std::process::Command::new("rustc").arg("--version"))?;
    println!("  ✓ rustc : {}", String::from_utf8_lossy(&rustc.stdout).trim());
    Ok(())
}

fn cmd_install(root: &PathBuf, force: bool) -> Result<()> {
    let venv = root.join(VENV_DIR);
    if venv.exists() && !force {
        println!("venv already exists at {}. Run `unai install --force` to recreate.", venv.display());
        println!("hint: `unai doctor` to verify.");
        return Ok(());
    }
    if force && venv.exists() {
        std::fs::remove_dir_all(&venv)
            .with_context(|| format!("failed to remove stale {venv:?}"))?;
        println!("removed stale venv {}.", venv.display());
    }

    println!("creating venv at {} ...", venv.display());
    let out = run(std::process::Command::new("python3").args(["-m", "venv", &VENV_DIR]).current_dir(root))?;
    if !out.status.success() {
        anyhow::bail!("python3 -m venv failed: {}", String::from_utf8_lossy(&out.stderr));
    }

    let py = venv_python(root).context("venv created but python not found")?;
    println!("editable-installing 'unai' runtime ...");
    let pip = run(std::process::Command::new(&py)
        .arg("-m").arg("pip").arg("install").arg("-q").arg("-e").arg(root)
        .current_dir(root))?;
    if !pip.status.success() {
        println!("warn: editable install failed (runtime not on PATH): {}", String::from_utf8_lossy(&pip.stderr));
    }
    println!("done. (unai doctor) to verify.");
    Ok(())
}

fn cmd_workspace(root: &PathBuf, cmd: WorkspaceCmd) -> Result<()> {
    match cmd {
        WorkspaceCmd::List => {
            println!("workspaces:");
            // Discover installed workspaces in ~/.unai/workspaces OR bundled src/unai/workspaces
            let ws_dir = root.join("src").join("unai").join("workspaces");
            let mut ids: Vec<String> = Vec::new();
            if let Ok(entries) = std::fs::read_dir(&ws_dir) {
                for e in entries.flatten() {
                    if let Some(name) = e.file_name().to_str() {
                        if name.ends_with(".py") && name != "__init__.py" {
                            ids.push(name.trim_end_matches(".py").to_string());
                        }
                    }
                }
            }
            // Also list installed packages from ~/.unai/workspaces/<id>/manifest.toml
            let home_ws = dirs_home().join(".unai").join("workspaces");
            if let Ok(entries) = std::fs::read_dir(&home_ws) {
                for e in entries.flatten() {
                    if let Some(name) = e.file_name().to_str() {
                        if e.path().join("manifest.toml").exists() {
                            ids.push(name.to_string());
                        }
                    }
                }
            }
            ids.sort();
            ids.dedup();
            for id in ids {
                let enabled = workspace_enabled(root, &id);
                let default_enabled = workspace_default_enabled(root, &id);
                let status = if enabled {
                    "● Enabled"
                } else {
                    "○ Disabled"
                };
                let dflt = if default_enabled { " (default: on)" } else { "" };
                println!("  {status:12} {id}{dflt}");
            }
        }
        WorkspaceCmd::Install { id, path } => cmd_workspace_install(root, &id, path.as_deref())?,
        WorkspaceCmd::Uninstall { id } => cmd_workspace_uninstall(root, &id)?,
        WorkspaceCmd::Update { id } => cmd_workspace_update(root, &id)?,
        WorkspaceCmd::Enable { id } => {
            let state = workspace_state_path(root, &id);
            std::fs::create_dir_all(state.parent().context("no state parent")?)?;
            std::fs::write(&state, "{\"enabled\": true}\n")?;
            println!("workspace '{id}' enabled (started on next runtime launch)");
        }
        WorkspaceCmd::Disable { id } => {
            let state = workspace_state_path(root, &id);
            std::fs::create_dir_all(state.parent().context("no state parent")?)?;
            std::fs::write(&state, "{\"enabled\": false}\n")?;
            println!("workspace '{id}' disabled (kept in registry)");
        }
        WorkspaceCmd::Start { id } => {
            let ws_path = installed_workspace_path(root, &id)?;
            run_lifecycle_hook(root, &id, &ws_path, "start")?;
            println!("workspace '{id}' started");
        }
        WorkspaceCmd::Stop { id } => {
            let ws_path = installed_workspace_path(root, &id)?;
            run_lifecycle_hook(root, &id, &ws_path, "stop")?;
            println!("workspace '{id}' stopped");
        }
    }
    Ok(())
}

/// Home directory (без внешней зависимости от home crate — берём из env).
fn dirs_home() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

/// Путь к установленному воркспейсу: сначала ~/.unai/workspaces/<id>,
/// затем (fallback) bundled src/unai/workspaces/<id>.py.
fn installed_workspace_path(root: &PathBuf, id: &str) -> Result<PathBuf> {
    let home_ws = dirs_home().join(".unai").join("workspaces").join(id);
    if home_ws.join("manifest.toml").exists() {
        return Ok(home_ws);
    }
    let bundled = workspace_module_path(root, id)?;
    Ok(bundled.parent().unwrap_or(root).to_path_buf())
}

/// Выполнить lifecycle-хук run.py:<hook>() в контексте воркспейса.
/// run.py кладём в sys.path (корень воркспейса), вызываем hook-функцию.
fn run_lifecycle_hook(root: &PathBuf, id: &str, ws_path: &PathBuf, hook: &str) -> Result<()> {
    let py = match venv_python(root) {
        Some(p) => p,
        None => anyhow::bail!("venv not found — run `unai install` first"),
    };
    let run_py = ws_path.join("run.py");
    if !run_py.exists() {
        // Воркспейс без lifecycle-хуков — пропускаем молча (не ошибка).
        return Ok(());
    }
    let code = format!(
        r#"
import sys, importlib.util
sys.path.insert(0, {ws:?})
spec = importlib.util.spec_from_file_location("ws_run", {run:?})
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
hook = getattr(mod, {hook:?}, None)
if hook is not None:
    hook(ctx={{"root": {root:?}, "id": {id:?}, "workspace": {ws:?}}})
"#,
        ws = ws_path.display().to_string(),
        run = run_py.display().to_string(),
        hook = hook,
        root = root.display().to_string(),
        id = id,
    );
    let out = run(std::process::Command::new(&py).arg("-c").arg(&code))?;
    if !out.status.success() {
        anyhow::bail!(
            "run.py:{hook} failed: {}",
            String::from_utf8_lossy(&out.stderr)
        );
    }
    Ok(())
}

/// Marketplace index: main/wsmarketplace/index.json → { id: {repo, ref, path, description} }
fn marketplace_index(root: &PathBuf) -> Result<serde_json::Value> {
    let idx = root.join("wsmarketplace").join("index.json");
    let raw = std::fs::read_to_string(&idx)
        .with_context(|| format!("read marketplace index {}", idx.display()))?;
    serde_json::from_str(&raw).context("parse marketplace index.json")
}

/// Клонировать (или скопировать локально) пакет воркспейса во временную папку.
/// Возвращает путь к папке `path` из записи индекса (обычно `workspace`).
fn fetch_workspace_package(root: &PathBuf, id: &str, local_path: Option<&str>) -> Result<PathBuf> {
    // 1) Локальный путь: --path <dir> (репо или сразу workspace/)
    if let Some(p) = local_path {
        let src = PathBuf::from(p);
        if !src.exists() {
            anyhow::bail!("--path {p} not found");
        }
        // Если в папке есть подпапка workspace/ — берём её, иначе саму папку.
        let pkg = src.join("workspace");
        return Ok(if pkg.exists() { pkg } else { src });
    }

    // 2) Локальный wsrepos/<id> (dev-режим)
    let wsrepos = dirs_home()
        .join("Desktop")
        .join("projects")
        .join("UnAI")
        .join("wsrepos")
        .join(id);
    if wsrepos.join("workspace").exists() {
        return Ok(wsrepos.join("workspace"));
    }

    // 3) Marketplace index → git clone в temp
    let index = marketplace_index(root)?;
    let entry = index
        .get(id)
        .with_context(|| format!("workspace '{id}' not found in wsmarketplace/index.json"))?;
    let repo = entry
        .get("repo")
        .and_then(|v| v.as_str())
        .context("index entry missing 'repo'")?;
    let pkg_path = entry
        .get("path")
        .and_then(|v| v.as_str())
        .unwrap_or("workspace");
    let tmp = std::env::temp_dir().join(format!("unai-ws-{id}"));
    if tmp.exists() {
        std::fs::remove_dir_all(&tmp).ok();
    }
    let out = run(
        std::process::Command::new("git")
            .args(["clone", "--depth", "1", &format!("https://github.com/{repo}.git"), tmp.to_str().unwrap()]),
    )?;
    if !out.status.success() {
        anyhow::bail!(
            "git clone {repo} failed: {}",
            String::from_utf8_lossy(&out.stderr)
        );
    }
    let pkg = tmp.join(pkg_path);
    if !pkg.exists() {
        anyhow::bail!("package path '{pkg_path}' not found in repo {repo}");
    }
    Ok(pkg)
}

fn cmd_workspace_install(root: &PathBuf, id: &str, local_path: Option<&str>) -> Result<()> {
    let pkg = fetch_workspace_package(root, id, local_path)?;

    // Куда кладём: ~/.unai/workspaces/<id>/
    let dest = dirs_home().join(".unai").join("workspaces").join(id);
    if dest.exists() {
        std::fs::remove_dir_all(&dest).ok();
    }
    std::fs::create_dir_all(&dest).context("create workspace install dir")?;
    copy_dir_recursive(&pkg, &dest)?;
    println!("installed workspace '{id}' -> {}", dest.display());

    // Lifecycle: install(ctx)
    run_lifecycle_hook(root, id, &dest, "install")?;

    // Данные: ~/.unai/data/<id>/
    let data_dir = dirs_home().join(".unai").join("data").join(id);
    std::fs::create_dir_all(&data_dir).context("create workspace data dir")?;
    println!("workspace data dir -> {}", data_dir.display());

    // Стартовый state: не enabled (default_enabled применяется при старте рантайма)
    let state = workspace_state_path(root, id);
    std::fs::create_dir_all(state.parent().context("no state parent")?)?;
    if !state.exists() {
        std::fs::write(&state, "{\"enabled\": false}\n")?;
    }
    println!("workspace '{id}' installed (disabled by default; `unai workspace enable {id}` to run)");
    Ok(())
}

fn cmd_workspace_uninstall(root: &PathBuf, id: &str) -> Result<()> {
    let dest = dirs_home().join(".unai").join("workspaces").join(id);
    if !dest.exists() {
        anyhow::bail!("workspace '{id}' is not installed (~/.unai/workspaces/{id})");
    }
    run_lifecycle_hook(root, id, &dest, "uninstall")?;
    std::fs::remove_dir_all(&dest).context("remove workspace dir")?;

    let data_dir = dirs_home().join(".unai").join("data").join(id);
    if data_dir.exists() {
        std::fs::remove_dir_all(&data_dir).ok();
    }
    let state = workspace_state_path(root, id);
    if state.exists() {
        std::fs::remove_file(&state).ok();
    }
    println!("workspace '{id}' uninstalled (code + data removed)");
    Ok(())
}

fn cmd_workspace_update(root: &PathBuf, id: &str) -> Result<()> {
    let dest = dirs_home().join(".unai").join("workspaces").join(id);
    if !dest.exists() {
        anyhow::bail!("workspace '{id}' is not installed — run `unai workspace install {id}` first");
    }
    // Переустановка: свежий пакет поверх старого (данные в ~/.unai/data не трогаем).
    let pkg = fetch_workspace_package(root, id, None)?;
    std::fs::remove_dir_all(&dest).context("remove old workspace dir")?;
    std::fs::create_dir_all(&dest).context("create workspace dir")?;
    copy_dir_recursive(&pkg, &dest)?;
    run_lifecycle_hook(root, id, &dest, "install")?;
    println!("workspace '{id}' updated (data preserved in ~/.unai/data/{id})");
    Ok(())
}

/// Рекурсивное копирование директории.
fn copy_dir_recursive(src: &PathBuf, dst: &PathBuf) -> Result<()> {
    for entry in std::fs::read_dir(src).context("read package dir")? {
        let entry = entry.context("read dir entry")?;
        let target = dst.join(entry.file_name());
        if entry.file_type().context("file type")?.is_dir() {
            std::fs::create_dir_all(&target)?;
            copy_dir_recursive(&entry.path(), &target)?;
        } else {
            std::fs::copy(entry.path(), &target)?;
        }
    }
    Ok(())
}

/// Путь к файлу состояния воркспейса: ~/.unai/workspaces/<id>/state.json
/// (рядом с кодом установленного воркспейса — ADR-0003).
fn workspace_state_path(root: &PathBuf, id: &str) -> PathBuf {
    let _ = root; // корень проекта не нужен: состояние живёт в ~/.unai
    dirs_home()
        .join(".unai")
        .join("workspaces")
        .join(id)
        .join("state.json")
}

/// Состояние воркспейса: enabled (включён, может стартовать) / disabled.
/// Если файла state.json нет — состояние берётся из `default_enabled` манифеста.
fn workspace_enabled(root: &PathBuf, id: &str) -> bool {
    let state = workspace_state_path(root, id);
    match std::fs::read_to_string(&state) {
        Ok(raw) => raw.contains("\"enabled\": true"),
        // Нет state-файла → доверяем рекомендации автора (default_enabled из манифеста)
        Err(_) => workspace_default_enabled(root, id),
    }
}

/// Прочитать `default_enabled` из манифеста воркспейса (через venv-python).
/// По умолчанию false — если модуль не найден или поле не задано.
fn workspace_default_enabled(root: &PathBuf, id: &str) -> bool {
    let py = match venv_python(root) {
        Some(p) => p,
        None => return false,
    };
    let code = format!(
        r#"
import json, sys
sys.path.insert(0, '{}')
try:
    import unai.workspaces.{id} as m
    for attr in dir(m):
        obj = getattr(m, attr)
        if hasattr(obj, 'default_enabled'):
            print(json.dumps(bool(obj.default_enabled)))
            break
    else:
        print('false')
except Exception:
    print('false')
"#,
        root.join("src").display()
    );
    match run(std::process::Command::new(&py).arg("-c").arg(&code)) {
        Ok(out) => String::from_utf8_lossy(&out.stdout).trim() == "true",
        Err(_) => false,
    }
}

// ---------------------------------------------------------------------------
// `unai config <ws_id>` — декларативный интерактивный конфигуратор.
// Читает settings-схему из манифеста воркспейса, строит UI, вызывает
// `set_settings` воркспейса. Без единой ветки под конкретный воркспейс.
// ---------------------------------------------------------------------------

/// Найти файл модуля воркспейса: src/unai/workspaces/<id>.py
fn workspace_module_path(root: &PathBuf, id: &str) -> Result<PathBuf> {
    let path = root
        .join("src")
        .join("unai")
        .join("workspaces")
        .join(format!("{id}.py"));
    if !path.exists() {
        anyhow::bail!("workspace '{id}' not found in src/unai/workspaces/");
    }
    Ok(path)
}

fn cmd_config(root: &PathBuf, id: &str) -> Result<()> {
    let module_path = workspace_module_path(root, id)?;
    println!(
        "loading settings schema for workspace '{id}' from {}",
        module_path.display()
    );

    // Загружаем манифест через venv-питон: импортируем модуль воркспейса
    // и просим его выдать settings-схему как JSON (значения — отдельно).
    let py = venv_python(root).context("venv not found — run `unai install` first")?;
    let code = format!(
        r#"
import json, sys
sys.path.insert(0, '{}')
from unai.workspaces.{id} import *
import unai.workspaces.{id} as m
# Если модуль экспортирует схему константой или манифестом, выводим её
schema = getattr(m, 'EXAMPLE_SETTINGS_SCHEMA', None)
if schema is None:
    for attr in dir(m):
        obj = getattr(m, attr)
        if hasattr(obj, 'to_dict') and callable(getattr(obj, 'to_dict', None)):
            schema = obj
            break
if schema is None:
    print(json.dumps({{"error": "no settings schema found"}}))
else:
    print(json.dumps(schema.to_dict()))
"#,
        root.join("src").display()
    );
    let out = run(std::process::Command::new(&py).arg("-c").arg(&code))?;
    if !out.status.success() {
        anyhow::bail!(
            "failed to load settings schema: {}",
            String::from_utf8_lossy(&out.stderr)
        );
    }
    let stdout = String::from_utf8_lossy(&out.stdout);
    let json_str = stdout.trim();
    let schema: serde_json::Value = serde_json::from_str(json_str)
        .map_err(|e| anyhow::anyhow!("schema parse failed: {e}\nraw: {json_str}"))?;

    if schema.get("error").is_some() {
        println!("workspace '{id}' has no settings schema (nothing to configure).");
        return Ok(());
    }

    let title = schema
        .get("title")
        .and_then(|v| v.as_str())
        .unwrap_or(id);
    println!("== {title} ==");

    let mut answers: serde_json::Map<String, serde_json::Value> = serde_json::Map::new();
    let items = schema.get("items").and_then(|v| v.as_object());

    if let Some(items) = items {
        for (key, item) in items {
            let item_title = item
                .get("title")
                .and_then(|v| v.as_str())
                .unwrap_or(key);
            let item_type = item
                .get("type")
                .and_then(|v| v.as_str())
                .unwrap_or("text");
            let default = item.get("default");

            match item_type {
                "choice" => {
                    let choices: Vec<String> = item
                        .get("choices")
                        .and_then(|v| v.as_array())
                        .map(|arr| {
                            arr.iter()
                                .filter_map(|c| c.as_str().map(String::from))
                                .collect()
                        })
                        .unwrap_or_default();
                    if choices.is_empty() {
                        // Динамический выбор — пока заглушка (provider в Phase 5).
                        println!("  [dynamic choice via provider — Phase 5] {item_title}");
                        continue;
                    }
                    let default_idx = if let Some(d) = default.and_then(|d| d.as_str()) {
                        choices.iter().position(|c| c == d).unwrap_or(0)
                    } else {
                        0
                    };
                    let sel = dialoguer::Select::with_theme(&dialoguer::theme::ColorfulTheme::default())
                        .with_prompt(item_title)
                        .items(&choices)
                        .default(default_idx)
                        .interact()?;
                    answers.insert(key.clone(), serde_json::Value::String(choices[sel].clone()));
                }
                "action" => {
                    let confirm = dialoguer::Confirm::with_theme(&dialoguer::theme::ColorfulTheme::default())
                        .with_prompt(format!("{item_title}? (выполнить действие)"))
                        .default(false)
                        .interact()?;
                    if confirm {
                        answers.insert(
                            key.clone(),
                            serde_json::Value::String("__trigger__".into()),
                        );
                    }
                }
                _ => {
                    // text / custom
                    let input = dialoguer::Input::<String>::with_theme(&dialoguer::theme::ColorfulTheme::default())
                        .with_prompt(item_title)
                        .default(
                            default
                                .and_then(|d| d.as_str())
                                .unwrap_or_default()
                                .to_string(),
                        )
                        .interact_text()?;
                    answers.insert(key.clone(), serde_json::Value::String(input));
                }
            }
        }
    }

    if answers.is_empty() {
        println!("no answers collected (schema empty).");
        return Ok(());
    }

    // Сохраняем в локальный стейт-файл воркспейса: .unai/workspaces/<id>/settings.json
    let state_dir = root.join(".unai").join("workspaces").join(id);
    std::fs::create_dir_all(&state_dir)
        .with_context(|| format!("create state dir {}", state_dir.display()))?;
    let settings_path = state_dir.join("settings.json");
    std::fs::write(
        &settings_path,
        serde_json::to_string_pretty(&serde_json::Value::Object(answers))?,
    )
    .with_context(|| format!("write {}", settings_path.display()))?;
    println!("saved settings -> {}", settings_path.display());

    Ok(())
}