#!/usr/bin/env bash
# install.sh — set up claude_brain on a fresh server
# Usage: bash install.sh
set -euo pipefail

REPO="https://github.com/cactixxx/brain"
DEST="${CLAUDE_BRAIN_INSTALL_DIR:-$HOME/.claude_brain}"
MODEL="nomic-embed-text"

info()  { echo "[claude_brain] $*"; }
error() { echo "[claude_brain] ERROR: $*" >&2; exit 1; }

# ── Plan ─────────────────────────────────────────────────────────────────────

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              claude_brain installer                          ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "This script will do the following:"
echo ""
echo "  1. Install system packages via apt-get:"
echo "       git, python3, python3-venv, sqlite3"
echo ""
echo "  2. Install Ollama (if not already installed)"
echo "       Downloads and runs the official Ollama install script"
echo "       Configures Ollama to listen on port 11334"
echo "       Enables and starts the Ollama systemd service"
echo ""
echo "  3. Pull the embedding model: $MODEL (~274 MB)"
echo "       CPU-only, no GPU required"
echo "       Skipped if the model is already present"
echo ""
echo "  4. Clone or update claude_brain"
echo "       Destination: $DEST"
echo "       Source:      $REPO"
echo ""
echo "  5. Create a Python virtual environment and install dependencies"
echo "       $DEST/.venv"
echo ""
echo "  6. Print the command to register claude_brain with Claude Code"
echo ""

read -r -p "Continue? [y/N] " reply
echo ""
case "$reply" in
    [yY][eE][sS]|[yY]) ;;
    *) echo "Aborted."; exit 0 ;;
esac

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

# Configure Ollama to listen on port 11334 (all interfaces)
OLLAMA_SERVICE="/etc/systemd/system/ollama.service"
if [ -f "$OLLAMA_SERVICE" ] && ! grep -q "OLLAMA_HOST" "$OLLAMA_SERVICE"; then
    sed -i '/^\[Service\]/a Environment="OLLAMA_HOST=0.0.0.0:11334"' "$OLLAMA_SERVICE"
    info "Set OLLAMA_HOST=0.0.0.0:11334 in $OLLAMA_SERVICE"
fi

# Enable and start the systemd service
systemctl daemon-reload
systemctl enable ollama
systemctl restart ollama

# Wait for Ollama to be ready
info "Waiting for Ollama to be ready..."
for i in $(seq 1 15); do
    if curl -sf http://localhost:11334/ &>/dev/null; then
        break
    fi
    sleep 2
done
curl -sf http://localhost:11334/ &>/dev/null || error "Ollama did not start in time"

# Pull the embedding model
if ollama list | grep -q "^$MODEL"; then
    info "Model $MODEL already present"
else
    info "Pulling $MODEL (this may take a minute)..."
    ollama pull "$MODEL"
fi

# ── claude_brain ─────────────────────────────────────────────────────────────

if [ -d "$DEST/.git" ]; then
    info "Updating existing install at $DEST..."
    git -C "$DEST" pull --ff-only
else
    info "Cloning claude_brain to $DEST..."
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
info "  claude mcp add claude_brain ~/.claude_brain/.venv/bin/python -- -m claude_brain.server --env CLAUDE_BRAIN_DB=~/.claude_brain/claude_brain.db"
info ""
info "Or copy the example MCP config:"
info "  cp ~/.claude_brain/.mcp.json.example /your/project/.mcp.json"
