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
        WorkspaceCmd::Add { id } => println!("workspace add: {id} (pending — marketplace in Phase 5)"),
        WorkspaceCmd::Remove { id } => println!("workspace remove: {id} (pending — marketplace in Phase 5)"),
    }
    Ok(())
}