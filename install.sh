#!/usr/bin/env bash
set -e

REPO="kasper-studios/UnAI"
INSTALL_DIR="${HOME}/.local/bin"
BINARY_NAME="unai"
UNAI_HOME="${HOME}/.unai"

echo "=== UnAI Installer ==="
echo ""

# Detect OS and arch
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)

case "$ARCH" in
    x86_64) ARCH="x86_64" ;;
    aarch64|arm64) ARCH="aarch64" ;;
    *) echo "Unsupported architecture: $ARCH"; exit 1 ;;
esac

case "$OS" in
    linux) OS="unknown-linux-musl" ;;
    darwin) OS="apple-darwin" ;;
    *) echo "Unsupported OS: $OS"; exit 1 ;;
esac

TARGET="${ARCH}-${OS}"
echo "Detected platform: $TARGET"

# Try to fetch latest release binary
echo "Checking for pre-built binary..."
LATEST_RELEASE=$(curl -sSL "https://api.github.com/repos/${REPO}/releases/latest" | grep '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/' || echo "")

if [ -n "$LATEST_RELEASE" ]; then
    DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${LATEST_RELEASE}/${BINARY_NAME}-${TARGET}"
    echo "Found release ${LATEST_RELEASE}, downloading binary..."
    
    mkdir -p "$INSTALL_DIR"
    if curl -fsSL "$DOWNLOAD_URL" -o "${INSTALL_DIR}/${BINARY_NAME}"; then
        chmod +x "${INSTALL_DIR}/${BINARY_NAME}"
        echo "✓ Binary installed to ${INSTALL_DIR}/${BINARY_NAME}"
    else
        echo "⚠ Pre-built binary not available for $TARGET, will build from source..."
        LATEST_RELEASE=""
    fi
fi

# Fallback: build from source
if [ -z "$LATEST_RELEASE" ]; then
    echo "Building from source (requires Rust toolchain)..."
    
    if ! command -v cargo &> /dev/null; then
        echo "ERROR: cargo not found. Install Rust from https://rustup.rs/ or use a pre-built release."
        exit 1
    fi
    
    TMP_DIR=$(mktemp -d)
    echo "Cloning repository to $TMP_DIR..."
    git clone --depth 1 "https://github.com/${REPO}.git" "$TMP_DIR"
    
    cd "$TMP_DIR"
    echo "Building UnAI CLI..."
    cargo build --release --manifest-path unai-cli/Cargo.toml
    
    mkdir -p "$INSTALL_DIR"
    cp "unai-cli/target/release/${BINARY_NAME}" "${INSTALL_DIR}/${BINARY_NAME}"
    chmod +x "${INSTALL_DIR}/${BINARY_NAME}"
    
    cd - > /dev/null
    rm -rf "$TMP_DIR"
    
    echo "✓ Built and installed to ${INSTALL_DIR}/${BINARY_NAME}"
fi

# Verify installation
if ! "${INSTALL_DIR}/${BINARY_NAME}" --version &> /dev/null; then
    echo "ERROR: Installation failed, binary not working"
    exit 1
fi

echo ""
echo "=== Installation Complete! ==="
echo ""
echo "UnAI CLI installed to: ${INSTALL_DIR}/${BINARY_NAME}"
echo ""
echo "Next steps:"
echo "  1. Make sure ${INSTALL_DIR} is in your PATH"
echo "  2. Run: unai --help"
echo "  3. Install example workspace: unai workspace install example"
echo ""
