#!/usr/bin/env bash
set -e

echo "=== UnAI Bootstrap Installer ==="

UNAI_HOME="${HOME}/.unai"
INSTALL_BIN="${HOME}/.local/bin/unai"
REPO_URL="https://github.com/kasper-studios/UnAI.git"
CLONE_DIR="${HOME}/.unai/src"

mkdir -p "${UNAI_HOME}/workspaces" "${UNAI_HOME}/data" "${HOME}/.local/bin"

if [ -d "${CLONE_DIR}/main" ]; then
    echo "Updating existing UnAI source at ${CLONE_DIR}..."
    cd "${CLONE_DIR}"
    git pull origin main
else
    echo "Cloning UnAI repository..."
    mkdir -p "${CLONE_DIR}"
    git clone "${REPO_URL}" "${CLONE_DIR}"
fi

cd "${CLONE_DIR}/main"

echo "Building UnAI CLI via Cargo..."
cargo build --release --manifest-path unai-cli/Cargo.toml

echo "Installing unai binary to ${INSTALL_BIN}..."
cp unai-cli/target/release/unai "${INSTALL_BIN}"
chmod +x "${INSTALL_BIN}"

echo "Setting up Python runtime venv..."
"${INSTALL_BIN}" install --force

echo ""
echo "=== Installation Complete! ==="
echo "Make sure ${HOME}/.local/bin is in your PATH."
echo "Try running: unai --help"
echo "Install example workspace: unai workspace install example"
