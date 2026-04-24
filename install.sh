#!/usr/bin/env bash
# install.sh — set up claude_brain on a fresh server
# Usage: bash install.sh
set -euo pipefail

REPO="https://github.com/cactixxx/claude_brain"
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
echo "  6. Add claude_brain to PATH in ~/.bashrc and ~/.zshrc"
echo ""
echo "  7. Print the command to register claude_brain with Claude Code"
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

# All ollama CLI commands must target port 11334
export OLLAMA_HOST="http://localhost:11334"

if ! command -v ollama &>/dev/null; then
    info "Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    info "Ollama already installed."
fi

# Configure Ollama to listen on port 11334 (all interfaces)
OLLAMA_SERVICE="/etc/systemd/system/ollama.service"
if [ -f "$OLLAMA_SERVICE" ] && ! grep -q "OLLAMA_HOST" "$OLLAMA_SERVICE"; then
    sed -i '/^\[Service\]/a Environment="OLLAMA_HOST=0.0.0.0:11334"' "$OLLAMA_SERVICE"
    info "Set OLLAMA_HOST=0.0.0.0:11334 in $OLLAMA_SERVICE"
fi

# Start Ollama only if it is not already responding
if curl -sf http://localhost:11334/ &>/dev/null; then
    info "Ollama is already running on port 11334 — leaving it alone."
else
    info "Starting Ollama via systemd..."
    systemctl daemon-reload
    systemctl enable ollama
    systemctl restart ollama

    info "Waiting for Ollama to be ready..."
    ready=0
    for i in $(seq 1 10); do
        if curl -sf http://localhost:11334/ &>/dev/null; then
            ready=1
            break
        fi
        sleep 1
    done
    if [ "$ready" -eq 0 ]; then
        error "Ollama did not start after 10 seconds. Please run: ollama serve"
    fi
fi

# Pull the embedding model if not already present
if ollama list 2>/dev/null | grep -q "^$MODEL"; then
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

# Add venv bin to PATH in shell rc files
EXPORT_LINE="export PATH=\"$DEST/.venv/bin:\$PATH\""
for RC in "$HOME/.bashrc" "$HOME/.zshrc"; do
    if [ -f "$RC" ] && ! grep -qF "$DEST/.venv/bin" "$RC"; then
        echo "$EXPORT_LINE" >> "$RC"
        info "Added claude_brain to PATH in $RC"
    fi
done

# ── Update .mcp.json.example with absolute paths ─────────────────────────────

sed -i \
    "s|\"command\":.*|\"command\": \"$DEST/.venv/bin/python\",|" \
    "$DEST/.mcp.json.example"
sed -i \
    "s|\"CLAUDE_BRAIN_DB\":.*|\"CLAUDE_BRAIN_DB\": \"$DEST/claude_brain.db\"|" \
    "$DEST/.mcp.json.example"
info "Updated .mcp.json.example with absolute paths for this user."

# ── Done ─────────────────────────────────────────────────────────────────────

info ""
info "Installation complete."
info ""
info "Register with Claude Code (run inside your project directory):"
info "  claude mcp add claude_brain $DEST/.venv/bin/python -- -m claude_brain.server --env CLAUDE_BRAIN_DB=$DEST/claude_brain.db"
info ""
info "Or copy the updated MCP config into your project:"
info "  cp $DEST/.mcp.json.example /your/project/.mcp.json"
info ""
info "── Verify it works ─────────────────────────────────────────────"
info ""
info "  cd /your/project"
info "  source ~/.bashrc"
info "  CLAUDE_BRAIN_DB=./claude_brain.db claude_brain list       # empty at first"
info "  # start Claude Code — it will call record_* tools automatically"
info "  claude_brain stats"
info "  claude_brain list"
info "  claude_brain show 1"
