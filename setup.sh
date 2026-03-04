#!/usr/bin/env bash
# =============================================================================
# Claude Automation Agent — Bare-Metal Setup Script
# Supports: Fedora, Ubuntu, Debian
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()     { error "$*"; exit 1; }

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$REPO_DIR/data"

# ---------------------------------------------------------------------------
# Detect OS and package manager
# ---------------------------------------------------------------------------
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS_ID="${ID:-unknown}"
        OS_FAMILY="${ID_LIKE:-$OS_ID}"
    else
        die "Cannot detect OS. /etc/os-release not found."
    fi

    if command -v dnf &>/dev/null; then
        PKG_INSTALL="sudo dnf install -y"
        PKG_UPDATE="sudo dnf check-update || true"
    elif command -v apt-get &>/dev/null; then
        PKG_INSTALL="sudo apt-get install -y"
        PKG_UPDATE="sudo apt-get update"
    else
        die "Unsupported package manager. Install Fedora, Ubuntu, or Debian."
    fi

    info "Detected OS: $OS_ID (family: $OS_FAMILY), using: $PKG_INSTALL"
}

# ---------------------------------------------------------------------------
# Install system dependencies
# ---------------------------------------------------------------------------
install_system_deps() {
    info "Installing system dependencies..."
    $PKG_UPDATE

    COMMON_DEPS="curl wget git python3 python3-pip golang"
    if echo "$PKG_INSTALL" | grep -q dnf; then
        $PKG_INSTALL $COMMON_DEPS python3-devel gcc
    else
        $PKG_INSTALL $COMMON_DEPS python3-dev gcc build-essential
    fi
}

# ---------------------------------------------------------------------------
# Install Node.js (for npx MCP servers)
# ---------------------------------------------------------------------------
install_nodejs() {
    if command -v node &>/dev/null; then
        info "Node.js already installed: $(node --version)"
        return
    fi
    info "Installing Node.js 20..."
    if echo "$PKG_INSTALL" | grep -q dnf; then
        sudo dnf module install -y nodejs:20
    else
        curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
        sudo apt-get install -y nodejs
    fi
    info "Node.js installed: $(node --version)"
}

# ---------------------------------------------------------------------------
# Install Ollama
# ---------------------------------------------------------------------------
install_ollama() {
    if command -v ollama &>/dev/null; then
        info "Ollama already installed: $(ollama --version 2>/dev/null || echo 'ok')"
        return
    fi
    info "Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    info "Ollama installed"
}

# ---------------------------------------------------------------------------
# Ensure Ollama service is running
# ---------------------------------------------------------------------------
start_ollama() {
    if systemctl is-active --quiet ollama 2>/dev/null; then
        info "Ollama service already running"
        return
    fi
    info "Starting Ollama service..."
    sudo systemctl enable --now ollama
    sleep 3  # Give Ollama time to initialize
}

# ---------------------------------------------------------------------------
# Pull LLM model
# ---------------------------------------------------------------------------
pull_model() {
    MODEL="${OLLAMA_MODEL:-qwen2.5:7b}"
    info "Pulling model '$MODEL' (this may take a while on first run)..."
    ollama pull "$MODEL"
    info "Model '$MODEL' ready"
}

# ---------------------------------------------------------------------------
# Install whatsapp-mcp (Go binary)
# ---------------------------------------------------------------------------
install_whatsapp_mcp() {
    BIN_PATH="$HOME/.local/bin/whatsapp-mcp"
    if [ -f "$BIN_PATH" ]; then
        info "whatsapp-mcp already installed at $BIN_PATH"
        return
    fi
    info "Building whatsapp-mcp from source..."
    mkdir -p "$HOME/.local/bin"
    TMP_DIR=$(mktemp -d)
    git clone --depth 1 https://github.com/lharries/whatsapp-mcp.git "$TMP_DIR/whatsapp-mcp"
    cd "$TMP_DIR/whatsapp-mcp"
    go build -o "$BIN_PATH" ./...
    cd "$REPO_DIR"
    rm -rf "$TMP_DIR"
    info "whatsapp-mcp installed at $BIN_PATH"
}

# ---------------------------------------------------------------------------
# Install Python dependencies
# ---------------------------------------------------------------------------
install_python_deps() {
    info "Installing Python dependencies..."
    VENV_DIR="$REPO_DIR/.venv"
    if [ ! -d "$VENV_DIR" ]; then
        python3 -m venv "$VENV_DIR"
    fi
    "$VENV_DIR/bin/pip" install --upgrade pip
    "$VENV_DIR/bin/pip" install -r "$REPO_DIR/agent/requirements.txt"
    info "Python deps installed in $VENV_DIR"
}

# ---------------------------------------------------------------------------
# Install NVIDIA Container Toolkit (for Docker GPU)
# ---------------------------------------------------------------------------
install_nvidia_container_toolkit() {
    if ! command -v nvidia-smi &>/dev/null; then
        warn "nvidia-smi not found. Skipping NVIDIA Container Toolkit install."
        warn "If you have an NVIDIA GPU, install drivers first."
        return
    fi
    if command -v nvidia-container-runtime &>/dev/null; then
        info "NVIDIA Container Toolkit already installed"
        return
    fi
    info "Installing NVIDIA Container Toolkit for Docker GPU passthrough..."
    if echo "$PKG_INSTALL" | grep -q dnf; then
        curl -s -L https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo \
            | sudo tee /etc/yum.repos.d/nvidia-container-toolkit.repo
        sudo dnf install -y nvidia-container-toolkit
    else
        distribution=$(. /etc/os-release && echo $ID$VERSION_ID)
        curl -s -L "https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list" \
            | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
        sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
    fi
    sudo nvidia-ctk runtime configure --runtime=docker
    sudo systemctl restart docker
    info "NVIDIA Container Toolkit installed"
}

# ---------------------------------------------------------------------------
# Create .env from template
# ---------------------------------------------------------------------------
setup_env() {
    if [ -f "$REPO_DIR/.env" ]; then
        info ".env already exists, skipping"
        return
    fi
    info "Creating .env from template..."
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
    warn "Edit $REPO_DIR/.env and fill in your values before running the agent."
}

# ---------------------------------------------------------------------------
# Create data directories
# ---------------------------------------------------------------------------
setup_data_dirs() {
    info "Creating data directories..."
    mkdir -p "$DATA_DIR"/{gmail,calendar,whatsapp}
    info "Data directories created at $DATA_DIR"
}

# ---------------------------------------------------------------------------
# Install systemd service and timer
# ---------------------------------------------------------------------------
install_systemd() {
    SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
    mkdir -p "$SYSTEMD_USER_DIR"

    VENV_DIR="$REPO_DIR/.venv"

    # Substitute paths in service file
    sed \
        -e "s|{{REPO_DIR}}|$REPO_DIR|g" \
        -e "s|{{VENV_DIR}}|$VENV_DIR|g" \
        -e "s|{{DATA_DIR}}|$DATA_DIR|g" \
        "$REPO_DIR/systemd/claude-agent.service" \
        > "$SYSTEMD_USER_DIR/claude-agent.service"

    cp "$REPO_DIR/systemd/claude-agent.timer" "$SYSTEMD_USER_DIR/claude-agent.timer"

    systemctl --user daemon-reload
    systemctl --user enable claude-agent.timer
    info "Systemd service and timer installed"
    info "Start with: systemctl --user start claude-agent.timer"
}

# ---------------------------------------------------------------------------
# Run one-time auth flows
# ---------------------------------------------------------------------------
run_setup_auth() {
    info "Running one-time authentication setup..."
    VENV_DIR="$REPO_DIR/.venv"
    cd "$REPO_DIR/agent"
    "$VENV_DIR/bin/python" claude-agent.py --setup
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    info "=== Claude Automation Agent — Setup ==="
    info "Repo: $REPO_DIR"
    echo

    detect_os
    install_system_deps
    install_nodejs
    install_ollama
    start_ollama
    pull_model
    install_whatsapp_mcp
    install_python_deps
    install_nvidia_container_toolkit
    setup_env
    setup_data_dirs
    install_systemd

    echo
    info "=== Setup complete ==="
    echo
    warn "Next steps:"
    echo "  1. Edit $REPO_DIR/.env (fill WHATSAPP_NOTIFY_NUMBER and optionally ANTHROPIC_API_KEY)"
    echo "  2. Run auth setup: bash setup.sh --auth"
    echo "  3. Start the agent: systemctl --user start claude-agent.timer"
    echo "  4. Check logs: journalctl --user -u claude-agent -f"
    echo "     or: tail -f $DATA_DIR/agent.log"
}

# Handle --auth flag
if [[ "${1:-}" == "--auth" ]]; then
    source "$REPO_DIR/.env" 2>/dev/null || true
    run_setup_auth
    exit 0
fi

main
