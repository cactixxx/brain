#!/usr/bin/env bash
# install.sh — set up claude_brain on a fresh server
# Usage: bash install.sh
set -euo pipefail

REPO="https://github.com/cactixxx/claude_brain"
DEST="${CLAUDE_BRAIN_INSTALL_DIR:-$HOME/.claude_brain}"
LLAMA_DIR="$HOME/llama.cpp"
MODEL_DIR="$LLAMA_DIR/models"
MODEL_FILE="$MODEL_DIR/nomic-embed-text-v1.5.f16.gguf"
MODEL_URL="https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.f16.gguf"
LLAMA_PORT=8080

info()  { echo "[claude_brain] $*"; }
error() { echo "[claude_brain] ERROR: $*" >&2; exit 1; }

# ── GPU detection ─────────────────────────────────────────────────────────────

detect_gpu() {
    # NVIDIA — check nvidia-smi first, then device nodes
    if command -v nvidia-smi &>/dev/null && nvidia-smi -L &>/dev/null 2>&1; then
        echo "nvidia"; return
    fi
    if ls /dev/nvidia0 &>/dev/null 2>&1; then
        echo "nvidia"; return
    fi
    # AMD — ROCm
    if command -v rocm-smi &>/dev/null && rocm-smi &>/dev/null 2>&1; then
        echo "amd"; return
    fi
    if [ -e /dev/kfd ]; then
        echo "amd"; return
    fi
    echo "none"
}

# ── Plan ─────────────────────────────────────────────────────────────────────

GPU=$(detect_gpu)

case "$GPU" in
    nvidia) GPU_LABEL="NVIDIA (CUDA)" ; CMAKE_GPU_FLAG="-DGGML_CUDA=ON" ;;
    amd)    GPU_LABEL="AMD (ROCm/HIP)" ; CMAKE_GPU_FLAG="-DGGML_HIPBLAS=ON" ;;
    *)      GPU_LABEL="none — CPU only" ; CMAKE_GPU_FLAG="-DGGML_NATIVE=ON" ;;
esac

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              claude_brain installer                          ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "This script will do the following:"
echo ""
echo "  1. Install system packages via apt-get:"
echo "       git, python3, python3-venv, sqlite3,"
echo "       cmake, build-essential, libcurl4-openssl-dev"
echo ""
echo "  2. Build llama.cpp from source"
echo "       Destination: $LLAMA_DIR"
echo "       GPU detected: $GPU_LABEL"
echo "       cmake flag:   $CMAKE_GPU_FLAG"
echo ""
echo "  3. Download embedding model (~270 MB)"
echo "       nomic-embed-text-v1.5.f16.gguf"
echo "       Destination: $MODEL_FILE"
echo "       Skipped if already present"
echo ""
echo "  4. Install llama-server as a systemd service (llamacpp-embed)"
echo "       Listens on port $LLAMA_PORT"
echo ""
echo "  5. Clone or update claude_brain"
echo "       Destination: $DEST"
echo "       Source:      $REPO"
echo ""
echo "  6. Create a Python virtual environment and install dependencies"
echo "       $DEST/.venv"
echo ""
echo "  7. Add claude_brain to PATH in ~/.bashrc and ~/.zshrc"
echo ""
echo "  8. Print the command to register claude_brain with Claude Code"
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
apt-get install -y -qq \
    git python3 python3-venv sqlite3 wget \
    cmake build-essential libcurl4-openssl-dev

# Python version check
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)'; then
    error "Python 3.11+ required (got $(python3 --version))"
fi
info "Python: $(python3 --version)"

# cmake version check (llama.cpp requires 3.14+)
CMAKE_VER=$(cmake --version | head -1 | awk '{print $3}')
info "cmake: $CMAKE_VER"

# ── llama.cpp ────────────────────────────────────────────────────────────────

if [ -d "$LLAMA_DIR/.git" ]; then
    info "Updating existing llama.cpp at $LLAMA_DIR..."
    git -C "$LLAMA_DIR" pull --ff-only
else
    info "Cloning llama.cpp to $LLAMA_DIR..."
    git clone https://github.com/ggml-org/llama.cpp "$LLAMA_DIR"
fi

info "Building llama.cpp ($GPU_LABEL)..."
cmake -B "$LLAMA_DIR/build" -S "$LLAMA_DIR" $CMAKE_GPU_FLAG
cmake --build "$LLAMA_DIR/build" --config Release -j "$(nproc)"

LLAMA_BIN="$LLAMA_DIR/build/bin/llama-server"
[ -x "$LLAMA_BIN" ] || error "Build succeeded but llama-server binary not found at $LLAMA_BIN"
info "llama-server built: $LLAMA_BIN"

# ── Embedding model ───────────────────────────────────────────────────────────

mkdir -p "$MODEL_DIR"
if [ -f "$MODEL_FILE" ]; then
    info "Model already present: $MODEL_FILE"
else
    info "Downloading nomic-embed-text-v1.5.f16.gguf (~270 MB)..."
    wget -O "$MODEL_FILE" "$MODEL_URL"
    info "Model saved to $MODEL_FILE"
fi

# ── llama-server systemd service ──────────────────────────────────────────────

SERVICE_FILE="/etc/systemd/system/llamacpp-embed.service"

NPROC=$(nproc)
info "Installing llamacpp-embed systemd service (threads: $NPROC)..."
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=llama.cpp embedding server for claude_brain
After=network.target
Wants=network.target

[Service]
Type=simple
ExecStart=$LLAMA_BIN \\
    -m $MODEL_FILE \\
    --embeddings \\
    --host 127.0.0.1 \\
    --port $LLAMA_PORT \\
    -c 2048 \\
    -t $NPROC
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable llamacpp-embed

if curl -sf "http://localhost:$LLAMA_PORT/health" &>/dev/null; then
    info "llama-server already running on port $LLAMA_PORT — restarting to pick up new config..."
    systemctl restart llamacpp-embed
else
    info "Starting llamacpp-embed..."
    systemctl start llamacpp-embed
fi

info "Waiting for llama-server to be ready..."
ready=0
for i in $(seq 1 30); do
    if curl -sf "http://localhost:$LLAMA_PORT/health" &>/dev/null; then
        ready=1; break
    fi
    sleep 2
done
[ "$ready" -eq 1 ] || error "llama-server did not start after 60 seconds. Check: journalctl -u llamacpp-embed"

info "llama-server is ready on port $LLAMA_PORT"

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
info "Embedding server: http://localhost:$LLAMA_PORT  (service: llamacpp-embed)"
info "Model:            $MODEL_FILE"
info "llama.cpp:        $LLAMA_DIR"
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
