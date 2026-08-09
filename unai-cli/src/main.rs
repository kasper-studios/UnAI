use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use colored::Colorize;
use std::path::PathBuf;

/// UnAI — a workspace-oriented runtime for autonomous AI agents.
/// The infrastructure CLI: install, doctor, update, workspace management.
#[derive(Parser)]
#[command(name = "unai", version, about)]
struct Cli {
    #[command(subcommand)]
    command: Option<Commands>,
    /// Start the MCP server over stdio (alias for `serve`; used by MCP clients)
    #[arg(long)]
    mcp: bool,
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
    /// Update UnAI CLI binary and Python runtime to latest version
    Update {
        /// Skip CLI binary update (only update Python runtime)
        #[arg(long)]
        runtime_only: bool,
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
    /// Start MCP server for connected AI agents
    Serve,
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
    /// Reset a workspace's session (forces login tools back; ADR-0004)
    ResetSession {
        #[arg(value_name = "WS_ID")]
        id: String,
    },
}

const VENV_DIR: &str = ".venv";
const PYPROJECT: &str = "pyproject.toml";
// Common Python executable names inside a venv, in priority order
const VENV_PY: &[&str] = &["bin/python", "Scripts/python.exe"];

/// Project root = Папка, содержащая pyproject.toml (ядро UnAI).
/// При прямом запуске бинарника CARGO_MANIFEST_DIR не задан.
/// В продакшене всегда используем ~/.unai/src/main (runtime install dir).
/// Fallback: поиск pyproject.toml от cwd (для dev-режима).
fn project_root() -> PathBuf {
    // 1. Если есть CARGO_MANIFEST_DIR (dev build) — используем его
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
    // 2. Продакшн: runtime всегда в ~/.unai/src/main
    let runtime = dirs_home().join(".unai").join("src").join("main");
    if runtime.join(PYPROJECT).exists() {
        return runtime;
    }
    // 3. Fallback: поиск от cwd (dev без CARGO_MANIFEST_DIR)
    let start = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let mut cur = Some(start.as_path());
    while let Some(d) = cur {
        if d.join(PYPROJECT).exists() {
            return d.to_path_buf();
        }
        cur = d.parent();
    }
    // 4. Последний шанс: runtime dir (пусть дальше упадёт с понятной ошибкой)
    runtime
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
        Some(Commands::Version) => cmd_version(&root),
        Some(Commands::Doctor) => cmd_doctor(&root),
        Some(Commands::Install { force }) => cmd_install(&root, force),
        Some(Commands::Update { runtime_only }) => cmd_update(&root, runtime_only),
        Some(Commands::Workspace { command }) => cmd_workspace(&root, command),
        Some(Commands::Config { id }) => cmd_config(&root, &id),
        Some(Commands::Serve) => cmd_serve(&root),
        None if cli.mcp => cmd_serve(&root),
        None => {
            println!(
                "\n  {}  {}\n",
                "⬡".cyan().bold(),
                "UnAI".cyan().bold()
            );
            println!(
                "  {}",
                "Workspace-oriented runtime for autonomous AI agents".dimmed()
            );
            println!();
            println!(
                "  Run {} for usage information.",
                "unai --help".yellow().bold()
            );
            println!(
                "  Run {} to start the MCP server.\n",
                "unai serve".yellow().bold()
            );
            Ok(())
        }
    }
}

fn cmd_version(_root: &PathBuf) -> Result<()> {
    println!(
        "{} {}",
        "unai-cli".cyan().bold(),
        env!("CARGO_PKG_VERSION").magenta()
    );
    println!(
        "{} {}",
        "runtime:".dimmed(),
        pyproject_version()
            .unwrap_or_else(|_| "unknown".into())
            .magenta()
    );
    println!("{} {}", "protocol:".dimmed(), "1.0".magenta());
    Ok(())
}

fn cmd_serve(_root: &PathBuf) -> Result<()> {
    // MCP server uses the runtime venv from ~/.unai/src/main/.venv, NOT the project-local .venv
    let unai_home = dirs_home().join(".unai");
    let runtime_dir = unai_home.join("src").join("main");
    
    let py = venv_python(&runtime_dir)
        .or_else(|| venv_python(_root)) // Fallback: project .venv
        .or_else(|| Some(PathBuf::from("python3"))) // system python3
        .context("python3 not found")?;
    
    // Run python -m unai.mcp with src/ appended to PYTHONPATH
    // (don't replace — keep existing venv's editable install paths)
    let status = std::process::Command::new(&py)
        .arg("-m")
        .arg("unai.mcp")
        .env("PYTHONPATH", {
            let src = runtime_dir.join("src");
            let existing = std::env::var("PYTHONPATH").unwrap_or_default();
            if existing.is_empty() { src.to_string_lossy().to_string() }
            else { format!("{}:{}", src.display(), existing) }
        })
        .status()?;
        
    if !status.success() {
        anyhow::bail!("MCP server exited with status: {}", status);
    }
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
    println!("{}", "UnAI Doctor".cyan().bold());
    println!();

    let py = match venv_python(root) {
        Some(p) => p,
        None => {
            println!(
                "  {} {}  {}",
                "✗".red().bold(),
                "venv".white(),
                format!("NOT FOUND (run {})", "unai install".yellow().bold()).red()
            );
            return Ok(());
        }
    };
    println!(
        "  {} {}  {}",
        "✓".green().bold(),
        "venv".white(),
        py.display().to_string().dimmed()
    );

    // venv python --version
    let ver = run(std::process::Command::new(&py)
        .arg("--version"))?;
    let python_ver = String::from_utf8_lossy(&ver.stdout);
    println!(
        "  {} {}  {}",
        "✓".green().bold(),
        "python".white(),
        python_ver.trim().magenta()
    );

    // runtime import check
    let imp = run(std::process::Command::new(&py)
        .arg("-c")
        .arg("import unai; print(unai.__file__ or 'ok')"))?;
    if imp.status.success() {
        println!(
            "  {} {}  {}",
            "✓".green().bold(),
            "runtime import".white(),
            "ok".green()
        );
    } else {
        println!(
            "  {} {}  {}",
            "✗".red().bold(),
            "runtime import".white(),
            "FAILED".red().bold()
        );
    }

    let rustc = run(std::process::Command::new("rustc").arg("--version"))?;
    println!(
        "  {} {}  {}",
        "✓".green().bold(),
        "rustc".white(),
        String::from_utf8_lossy(&rustc.stdout).trim().magenta()
    );
    Ok(())
}


fn cmd_install(root: &PathBuf, force: bool) -> Result<()> {
    let venv = root.join(VENV_DIR);
    if venv.exists() && !force {
        println!(
            "venv already exists at {}.",
            venv.display().to_string().dimmed()
        );
        println!(
            "Run {} to recreate.",
            "unai install --force".yellow().bold()
        );
        println!(
            "hint: {} to verify.",
            "unai doctor".yellow().bold()
        );
        return Ok(());
    }
    if force && venv.exists() {
        std::fs::remove_dir_all(&venv)
            .with_context(|| format!("failed to remove stale {venv:?}"))?;
        println!(
            "removed stale venv {}.",
            venv.display().to_string().dimmed()
        );
    }

    println!(
        "creating venv at {} ...",
        venv.display().to_string().dimmed()
    );
    let out = run(std::process::Command::new("python3").args(["-m", "venv", &VENV_DIR]).current_dir(root))?;
    if !out.status.success() {
        anyhow::bail!("python3 -m venv failed: {}", String::from_utf8_lossy(&out.stderr));
    }

    let py = venv_python(root).context("venv created but python not found")?;
    println!("editable-installing {} runtime ...", "unai".cyan());
    let pip = run(std::process::Command::new(&py)
        .arg("-m").arg("pip").arg("install").arg("-q").arg("-e").arg(root)
        .current_dir(root))?;
    if !pip.status.success() {
        println!(
            "{} editable install failed (runtime not on PATH): {}",
            "warn:".yellow().bold(),
            String::from_utf8_lossy(&pip.stderr)
        );
    }
    println!(
        "{}  ({} to verify.)",
        "done.".green().bold(),
        "unai doctor".yellow().bold()
    );
    Ok(())
}


fn cmd_update(_root: &PathBuf, runtime_only: bool) -> Result<()> {
    println!("\n{}\n", "=== UnAI Update ===".cyan().bold());

    // 1. Update CLI binary (unless --runtime-only)
    if !runtime_only {
        println!("Checking for CLI binary updates...");
        let current_exe = std::env::current_exe().context("cannot determine current binary path")?;
        
        // Try to fetch latest release from GitHub.
        // Не используем api.github.com (анонимный rate-limit 60/ч -> 403).
        // Идём через HTTPS-редирект https://github.com/<repo>/releases/latest
        // -> .../releases/tag/<tag> (без лимитов, надёжно).
        let repo = "kasper-studios/UnAI";
        let redirect_url = format!("https://github.com/{repo}/releases/latest");
        let tag = match reqwest::blocking::Client::new()
            .get(&redirect_url)
            .header(reqwest::header::USER_AGENT, "unai-cli/update")
            .send()
        {
            Ok(resp) => {
                let final_url = resp.url().to_string();
                // final_url = https://github.com/<repo>/releases/tag/<tag>
                final_url
                    .rsplit('/')
                    .next()
                    .map(|s| s.to_string())
                    .filter(|t| !t.is_empty() && t != "latest")
            }
            Err(e) => {
                println!(
                    "  {} Failed to check for updates: {e}",
                    "⚠".yellow().bold()
                );
                println!("  Skipping CLI update");
                return update_python_runtime();
            }
        };

        if let Some(tag) = tag {
            println!(
                "  Latest release: {}",
                tag.magenta()
            );

            // Detect platform
            let os = std::env::consts::OS;
            let arch = std::env::consts::ARCH;
            let (targets, gnu_fallback) = match (os, arch) {
                ("linux", "x86_64") => (["x86_64-unknown-linux-musl"], true),
                ("linux", "aarch64") => (["aarch64-unknown-linux-musl"], true),
                ("macos", "x86_64") => (["x86_64-apple-darwin"], false),
                ("macos", "aarch64") => (["aarch64-apple-darwin"], false),
                _ => {
                    println!(
                        "  {} Pre-built binary not available for {os}-{arch}",
                        "⚠".yellow().bold()
                    );
                    println!("  Skipping CLI update (use source build manually if needed)");
                    return update_python_runtime();
                }
            };
            // musl обычно недоступен для system-rustc-сборок — fallback на gnu.
            let gnu_target: Option<&str> = if gnu_fallback && os == "linux" {
                match arch {
                    "x86_64" => Some("x86_64-unknown-linux-gnu"),
                    "aarch64" => Some("aarch64-unknown-linux-gnu"),
                    _ => None,
                }
            } else {
                None
            };

            let mut downloaded = false;
            let mut attempts: Vec<&str> = Vec::new();
            attempts.push(targets[0]);
            if let Some(g) = gnu_target {
                attempts.push(g);
            }
            for t in attempts {
                let download_url = format!(
                    "https://github.com/{repo}/releases/download/{tag}/unai-{t}"
                );
                println!(
                    "  Downloading {} ...",
                    download_url.dimmed()
                );
                match reqwest::blocking::Client::new()
                    .get(&download_url)
                    .header(reqwest::header::USER_AGENT, "unai-cli/update")
                    .send()
                {
                    Ok(resp) if resp.status().is_success() => {
                        let bytes = match resp.bytes() {
                            Ok(b) => b,
                            Err(e) => {
                                println!(
                                    "  {} Download failed (read): {e}",
                                    "⚠".yellow().bold()
                                );
                                continue;
                            }
                        };

                        // Write to temp file, then replace current binary
                        let temp_path = current_exe.with_extension("new");
                        if let Err(e) = std::fs::write(&temp_path, &bytes) {
                            println!(
                                "  {} Write failed: {e}",
                                "⚠".yellow().bold()
                            );
                            continue;
                        }

                        #[cfg(unix)]
                        {
                            use std::os::unix::fs::PermissionsExt;
                            let mut perms = match std::fs::metadata(&temp_path) {
                                Ok(m) => m.permissions(),
                                Err(e) => {
                                    println!(
                                        "  {} chmod metadata failed: {e}",
                                        "⚠".yellow().bold()
                                    );
                                    continue;
                                }
                            };
                            perms.set_mode(0o755);
                            if let Err(e) = std::fs::set_permissions(&temp_path, perms) {
                                println!(
                                    "  {} chmod failed: {e}",
                                    "⚠".yellow().bold()
                                );
                                continue;
                            }
                        }

                        // Atomic replace
                        match std::fs::rename(&temp_path, &current_exe) {
                            Ok(_) => {
                                println!(
                                    "  {} CLI binary updated to {} (unai-{t})",
                                    "✓".green().bold(),
                                    tag.magenta()
                                );
                                downloaded = true;
                            }
                            Err(e) => println!(
                                "  {} rename failed: {e}",
                                "⚠".yellow().bold()
                            ),
                        }
                        break;
                    }
                    Ok(resp) => {
                        println!(
                            "  {} Binary not found for {t} ({})",
                            "⚠".yellow().bold(),
                            resp.status()
                        );
                    }
                    Err(e) => {
                        println!(
                            "  {} Download failed: {e}",
                            "⚠".yellow().bold()
                        );
                    }
                }
            }
            if !downloaded {
                println!("  Skipping CLI update");
            }
        } else {
            println!(
                "  {} No releases found",
                "⚠".yellow().bold()
            );
            println!("  Skipping CLI update");
        }
        println!();
    }

    // 2. Update Python runtime
    update_python_runtime()
}

fn update_python_runtime() -> Result<()> {
    println!("Updating Python runtime...");
    
    let unai_home = dirs_home().join(".unai");
    let src_dir = unai_home.join("src").join("main");
    
    if src_dir.exists() {
        println!("  Pulling latest changes from GitHub...");
        let out = run(
            std::process::Command::new("git")
                .args(["pull", "origin", "main"])
                .current_dir(&src_dir)
        )?;
        
        if !out.status.success() {
            println!(
                "  {} git pull failed: {}",
                "⚠".yellow().bold(),
                String::from_utf8_lossy(&out.stderr)
            );
            return Ok(());
        }
        
        let stdout = String::from_utf8_lossy(&out.stdout);
        if stdout.contains("Already up to date") {
            println!(
                "  {} Runtime already up to date",
                "✓".green().bold()
            );
        } else {
            println!(
                "  {} Runtime updated",
                "✓".green().bold()
            );
            
            // Reinstall Python package
            println!("  Reinstalling Python package...");
            if let Some(py) = venv_python(&src_dir) {
                let pip = run(
                    std::process::Command::new(&py)
                        .args(["-m", "pip", "install", "-q", "-e", "."])
                        .current_dir(&src_dir)
                )?;
                
                if pip.status.success() {
                    println!(
                        "  {} Package reinstalled",
                        "✓".green().bold()
                    );
                } else {
                    println!(
                        "  {} Package reinstall failed: {}",
                        "⚠".yellow().bold(),
                        String::from_utf8_lossy(&pip.stderr)
                    );
                }
            }
        }
    } else {
        println!(
            "  No existing runtime installation found at {}",
            src_dir.display().to_string().dimmed()
        );
        println!("  Installing runtime from GitHub...");
        
        std::fs::create_dir_all(&unai_home.join("src"))?;
        
        let out = run(
            std::process::Command::new("git")
                .args([
                    "clone",
                    "--depth", "1",
                    "https://github.com/kasper-studios/UnAI.git",
                    src_dir.to_str().unwrap()
                ])
        )?;
        
        if !out.status.success() {
            anyhow::bail!("git clone failed: {}", String::from_utf8_lossy(&out.stderr));
        }
        
        println!(
            "  {} Runtime cloned",
            "✓".green().bold()
        );
        
        // Create venv and install
        println!("  Creating venv...");
        let venv_out = run(
            std::process::Command::new("python3")
                .args(["-m", "venv", ".venv"])
                .current_dir(&src_dir)
        )?;
        
        if !venv_out.status.success() {
            anyhow::bail!("venv creation failed: {}", String::from_utf8_lossy(&venv_out.stderr));
        }
        
        if let Some(py) = venv_python(&src_dir) {
            println!("  Installing runtime package...");
            let pip = run(
                std::process::Command::new(&py)
                    .args(["-m", "pip", "install", "-q", "-e", "."])
                    .current_dir(&src_dir)
            )?;
            
            if pip.status.success() {
                println!(
                    "  {} Runtime installed",
                    "✓".green().bold()
                );
            } else {
                println!(
                    "  {} Package install failed: {}",
                    "⚠".yellow().bold(),
                    String::from_utf8_lossy(&pip.stderr)
                );
            }
        }
    }
    
    println!(
        "\n{}", "=== Update Complete ===".cyan().bold()
    );
    println!(
        "Run {} to verify.",
        "unai --version".yellow().bold()
    );
    Ok(())
}


fn cmd_workspace(root: &PathBuf, cmd: WorkspaceCmd) -> Result<()> {
    match cmd {
        WorkspaceCmd::List => {
            println!("{}", "Workspaces:".cyan().bold());
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
            // Also list internal workspaces from internalws/
            let internal_dir = root.join("internalws");
            if let Ok(entries) = std::fs::read_dir(&internal_dir) {
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
            if ids.is_empty() {
                println!("  {}", "(no workspaces found)".dimmed());
            }
            for id in ids {
                let enabled = workspace_enabled(root, &id);
                let default_enabled = workspace_default_enabled(root, &id);
                if enabled {
                    let dflt = if default_enabled {
                        " (default: on)".dimmed().to_string()
                    } else {
                        String::new()
                    };
                    println!(
                        "  {} {} {}{}",
                        "●".green().bold(),
                        "Enabled ".green(),
                        id.cyan().bold(),
                        dflt
                    );
                } else {
                    let dflt = if default_enabled {
                        " (default: on)".dimmed().to_string()
                    } else {
                        String::new()
                    };
                    println!(
                        "  {} {} {}{}",
                        "○".dimmed(),
                        "Disabled".dimmed(),
                        id.cyan(),
                        dflt
                    );
                }
            }
        }
        WorkspaceCmd::Install { id, path } => cmd_workspace_install(root, &id, path.as_deref())?,
        WorkspaceCmd::Uninstall { id } => cmd_workspace_uninstall(root, &id)?,
        WorkspaceCmd::Update { id } => cmd_workspace_update(root, &id)?,
        WorkspaceCmd::Enable { id } => {
            let state = workspace_state_path(root, &id);
            std::fs::create_dir_all(state.parent().context("no state parent")?)?;
            std::fs::write(&state, "{\"enabled\": true}\n")?;
            println!(
                "{} workspace {} enabled (started on next runtime launch)",
                "✓".green().bold(),
                id.cyan().bold()
            );
        }
        WorkspaceCmd::Disable { id } => {
            let state = workspace_state_path(root, &id);
            std::fs::create_dir_all(state.parent().context("no state parent")?)?;
            std::fs::write(&state, "{\"enabled\": false}\n")?;
            println!(
                "{} workspace {} disabled (kept in registry)",
                "✓".green().bold(),
                id.cyan().bold()
            );
        }
        WorkspaceCmd::ResetSession { id } => {
            cmd_reset_session(root, &id)?;
        }
    }
    Ok(())
}


/// Remove a workspace's auth session data (ADR-0004).
/// Deletes `~/.unai/data/<id>/session.json` (and any `tokens/` subdir) so that
/// the next runtime load sees state `none` and `login`-tool reappears.
fn cmd_reset_session(root: &PathBuf, id: &str) -> Result<()> {
    let _ = root; // сессия живёт в ~/.unai/data, не в корне проекта
    let data_dir = dirs_home().join(".unai").join("data").join(id);
    let session_file = data_dir.join("session.json");

    let mut removed_any = false;
    if session_file.exists() {
        std::fs::remove_file(&session_file)
            .with_context(|| format!("remove session file {}", session_file.display()))?;
        removed_any = true;
        println!(
            "  removed {}",
            session_file.display().to_string().dimmed()
        );
    }
    let tokens_dir = data_dir.join("tokens");
    if tokens_dir.exists() {
        std::fs::remove_dir_all(&tokens_dir)
            .with_context(|| format!("remove tokens dir {}", tokens_dir.display()))?;
        removed_any = true;
        println!(
            "  removed {}",
            tokens_dir.display().to_string().dimmed()
        );
    }
    if !removed_any {
        println!(
            "workspace {} has no saved session (nothing to reset).",
            id.cyan().bold()
        );
    }
    println!(
        "{} session reset: login tools for {} will reappear on next runtime load (ADR-0004).",
        "✓".green().bold(),
        id.cyan().bold()
    );
    Ok(())
}


/// Home directory (без внешней зависимости от home crate — берём из env).
fn dirs_home() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
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


/// Marketplace index: { id: {repo, ref, path, description} }
/// Берётся из ОСНОВНОЙ репы (kasper-studios/UnAI): локальная папка
/// `wsmarketplace/index.json` — dev-оверрайд; при её отсутствии индекс
/// скачивается с raw.githubusercontent.com.
fn marketplace_index(root: &PathBuf) -> Result<serde_json::Value> {
    let idx = root.join("wsmarketplace").join("index.json");

    let raw: String = if idx.exists() {
        std::fs::read_to_string(&idx)
            .with_context(|| format!("read marketplace index {}", idx.display()))?
    } else {
        // Индекс живёт в основной репе; тяну raw-файл с GitHub.
        let url = "https://raw.githubusercontent.com/kasper-studios/UnAI/main/wsmarketplace/index.json";
        let body = reqwest::blocking::get(url)
            .with_context(|| format!("fetch marketplace index from {url}"))?
            .error_for_status()
            .context("marketplace index HTTP error")?
            .text()
            .context("marketplace index body")?;
        body
    };
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

    // 2) Marketplace index → git clone в temp
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
    println!(
        "installed workspace {} → {}",
        id.cyan().bold(),
        dest.display().to_string().dimmed()
    );

    // Lifecycle: install(ctx)
    run_lifecycle_hook(root, id, &dest, "install")?;

    // Данные: ~/.unai/data/<id>/
    let data_dir = dirs_home().join(".unai").join("data").join(id);
    std::fs::create_dir_all(&data_dir).context("create workspace data dir")?;
    println!(
        "workspace data dir → {}",
        data_dir.display().to_string().dimmed()
    );

    // Стартовый state: не enabled (default_enabled применяется при старте рантайма)
    let state = workspace_state_path(root, id);
    std::fs::create_dir_all(state.parent().context("no state parent")?)?;
    if !state.exists() {
        std::fs::write(&state, "{\"enabled\": false}\n")?;
    }
    println!(
        "{} workspace {} installed (disabled by default; {} to run)",
        "✓".green().bold(),
        id.cyan().bold(),
        format!("unai workspace enable {id}").yellow().bold()
    );
    Ok(())
}


fn cmd_workspace_uninstall(root: &PathBuf, id: &str) -> Result<()> {
    let dest = dirs_home().join(".unai").join("workspaces").join(id);
    if !dest.exists() {
        anyhow::bail!("workspace '{}' is not installed (~/.unai/workspaces/{})", id, id);
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
    println!(
        "{} workspace {} uninstalled (code + data removed)",
        "✓".green().bold(),
        id.cyan().bold()
    );
    Ok(())
}


fn cmd_workspace_update(root: &PathBuf, id: &str) -> Result<()> {
    let dest = dirs_home().join(".unai").join("workspaces").join(id);
    if !dest.exists() {
        anyhow::bail!(
            "workspace '{}' is not installed — run `unai workspace install {}` first",
            id, id
        );
    }
    // Переустановка: свежий пакет поверх старого (данные в ~/.unai/data не трогаем).
    let pkg = fetch_workspace_package(root, id, None)?;
    std::fs::remove_dir_all(&dest).context("remove old workspace dir")?;
    std::fs::create_dir_all(&dest).context("create workspace dir")?;
    copy_dir_recursive(&pkg, &dest)?;
    run_lifecycle_hook(root, id, &dest, "install")?;
    println!(
        "{} workspace {} updated (data preserved in {})",
        "✓".green().bold(),
        id.cyan().bold(),
        format!("~/.unai/data/{id}").dimmed()
    );
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
    // First try manifest.toml (for internal workspaces)
    let internal_manifest = root.join("internalws").join(id).join("manifest.toml");
    if internal_manifest.exists() {
        if let Ok(content) = std::fs::read_to_string(&internal_manifest) {
            if content.contains("default_enabled = true") {
                return true;
            }
        }
    }

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
        "loading settings schema for workspace {} from {}",
        id.cyan().bold(),
        module_path.display().to_string().dimmed()
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
        println!(
            "workspace {} has no settings schema (nothing to configure).",
            id.cyan().bold()
        );
        return Ok(());
    }

    let title = schema
        .get("title")
        .and_then(|v| v.as_str())
        .unwrap_or(id);
    println!("\n{}\n", format!("== {title} ==").cyan().bold());

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
                        println!(
                            "  {} {item_title}",
                            "[dynamic choice via provider — Phase 5]".dimmed()
                        );
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
                        .with_prompt(format!("{item_title}? (execute action)"))
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
        println!(
            "no answers collected ({}).",
            "schema empty".dimmed()
        );
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
    println!(
        "{} saved settings → {}",
        "✓".green().bold(),
        settings_path.display().to_string().dimmed()
    );

    Ok(())
}
