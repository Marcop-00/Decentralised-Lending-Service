#!/usr/bin/env bash

# Exit on error
set -e

echo "📦 Installing Node.js dependencies..."
npm ci

echo "🐍 Creating Python virtual environment (.venv)..."
python3 -m venv .venv

echo "📥 Installing Python dependencies inside .venv..."
./.venv/bin/pip install -r python/requirements.txt

echo "🔨 Compiling Smart Contracts..."
npm run compile

# ── Geth auto-download ────────────────────────────────────────────────────────
# Pinned to the pre-PoS Clique implementation used by the course genesis.
GETH_VERSION="1.13.14"
GETH_COMMIT="2bd6bd01"
GETH_DEST="private-chain/geth"
GETH_BASE="https://gethstore.blob.core.windows.net/builds"

_download_geth() {
  local os_name arch fname url
  case "$(uname -s)" in
    Darwin) os_name="darwin" ;;
    Linux)  os_name="linux"  ;;
    *)
      echo "⚠️  Unsupported OS '$(uname -s)'. Place geth ${GETH_VERSION} manually at ${GETH_DEST}."
      return
      ;;
  esac
  case "$(uname -m)" in
    x86_64|amd64)   arch="amd64" ;;
    arm64|aarch64)  arch="arm64" ;;
    *)
      echo "⚠️  Unsupported arch '$(uname -m)'. Place geth ${GETH_VERSION} manually at ${GETH_DEST}."
      return
      ;;
  esac

  fname="geth-${os_name}-${arch}-${GETH_VERSION}-${GETH_COMMIT}.tar.gz"
  url="${GETH_BASE}/${fname}"

  echo "  → Downloading geth ${GETH_VERSION} (${os_name}/${arch})..."
  TMP_DIR=$(mktemp -d)
  curl -fsSL "${url}" -o "${TMP_DIR}/${fname}"
  tar -xzf "${TMP_DIR}/${fname}" -C "${TMP_DIR}"
  mv "${TMP_DIR}/geth-${os_name}-${arch}-${GETH_VERSION}-${GETH_COMMIT}/geth" "${GETH_DEST}"
  chmod +x "${GETH_DEST}"
  rm -rf "${TMP_DIR}"
  echo "  ✔ geth ${GETH_VERSION} installed at ${GETH_DEST}"
}

echo "🔗 Checking Geth binary..."
if [ -x "${GETH_DEST}" ] && "${GETH_DEST}" version 2>/dev/null | grep -q "Version: ${GETH_VERSION}"; then
  echo "  ✔ geth ${GETH_VERSION} already present"
else
  _download_geth
fi
# ─────────────────────────────────────────────────────────────────────────────

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Start the private chain (Terminal 1):"
echo "       cd private-chain"
echo "       ./geth --datadir=./data init project2526genesis.json"
echo "       ./geth --datadir=./data --keystore=./keystore --networkid=202526 \\"
echo "         --http --http.addr=127.0.0.1 --http.port=8545 --http.api=eth,net,web3 \\"
echo "         --mine --miner.gasprice=100000000 \\"
echo "         --miner.etherbase=d278d247a52c550508ea2b2c9321d816238fb523 \\"
echo "         --unlock d278d247a52c550508ea2b2c9321d816238fb523 --password password.txt \\"
echo "         --allow-insecure-unlock --ipcdisable"
echo ""
echo "  2. Deploy contracts (Terminal 2):"
echo "       ./.venv/bin/python python/setup.py"
echo ""
echo "Use ./.venv/bin/python instead of python3 to run scripts."
