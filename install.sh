#!/usr/bin/env bash
# install.sh — set up project-brain on a fresh server
# Usage: bash install.sh
set -euo pipefail

REPO="https://github.com/cactixxx/brain"
DEST="${BRAIN_INSTALL_DIR:-$HOME/.brain}"
MODEL="nomic-embed-text"

info()  { echo "[brain] $*"; }
error() { echo "[brain] ERROR: $*" >&2; exit 1; }

# ── Prerequisites ────────────────────────────────────────────────────────────

info "Installing system packages..."
apt-get update -qq
apt-get install -y -qq git python3 python3-venv sqlite3

# Python version check
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)'; then
    error "Python 3.11+ required (got $(python3 --version))"
fi
info "Python: $(python3 --version)"

# ── Ollama ───────────────────────────────────────────────────────────────────

if ! command -v ollama &>/dev/null; then
    info "Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    info "Ollama already installed: $(ollama --version)"
fi

# Enable and start the systemd service
systemctl enable ollama
systemctl start ollama

# Wait for Ollama to be ready
info "Waiting for Ollama to be ready..."
for i in $(seq 1 15); do
    if curl -sf http://localhost:11434/ &>/dev/null; then
        break
    fi
    sleep 2
done
curl -sf http://localhost:11434/ &>/dev/null || error "Ollama did not start in time"

# Pull the embedding model
if ollama list | grep -q "^$MODEL"; then
    info "Model $MODEL already present"
else
    info "Pulling $MODEL (this may take a minute)..."
    ollama pull "$MODEL"
fi

# ── brain ────────────────────────────────────────────────────────────────────

if [ -d "$DEST/.git" ]; then
    info "Updating existing install at $DEST..."
    git -C "$DEST" pull --ff-only
else
    info "Cloning brain to $DEST..."
    git clone "$REPO" "$DEST"
fi

cd "$DEST"
python3 -m venv .venv
.venv/bin/pip install -q -e .

# ── Done ─────────────────────────────────────────────────────────────────────

info ""
info "Installation complete."
info ""
info "Register with Claude Code (run inside your project directory):"
info "  claude mcp add project-brain $DEST/.venv/bin/python -- -m brain.server --env BRAIN_DB=./brain.db"
info ""
info "Or copy the example MCP config:"
info "  cp $DEST/.mcp.json.example /your/project/.mcp.json"
