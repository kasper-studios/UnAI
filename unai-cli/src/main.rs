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
    /// Register a workspace package
    Add {
        #[arg(value_name = "WS_ID")]
        id: String,
    },
    /// Remove a workspace
    Remove {
        #[arg(value_name = "WS_ID")]
        id: String,
    },
}

const VENV_DIR: &str = ".venv";
const PYPROJECT: &str = "pyproject.toml";
// Common Python executable names inside a venv, in priority order
const VENV_PY: &[&str] = &["bin/python", "Scripts/python.exe"];

/// Project root = directory containing Cargo.toml's parent (unai-cli/../).
fn project_root() -> PathBuf {
    let cargo_manifest = PathBuf::from(
        std::env::var("CARGO_MANIFEST_DIR").unwrap_or_else(|_| ".".into()),
    );
    // CARGO_MANIFEST_DIR points to <root>/unai-cli, so the project root is its parent.
    cargo_manifest
        .parent()
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| cargo_manifest.clone())
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
            // Discover userland workspaces
            let ws_dir = root.join("src").join("unai").join("workspaces");
            if let Ok(entries) = std::fs::read_dir(ws_dir) {
                for e in entries.flatten() {
                    if let Some(name) = e.file_name().to_str() {
                        if name.ends_with(".py") && name != "__init__.py" {
                            println!("  - {}", name.trim_end_matches(".py"));
                        }
                    }
                }
            }
        }
        WorkspaceCmd::Add { id } => {
            println!("workspace add: {id} (pending — marketplace in Phase 5)")
        }
        WorkspaceCmd::Remove { id } => {
            println!("workspace remove: {id} (pending — marketplace in Phase 5)")
        }
    }
    Ok(())
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