#!/usr/bin/env bash

# Exit on error
set -e

echo "📦 Installing Node.js dependencies..."
npm install

echo "🐍 Creating Python virtual environment (.venv)..."
python3 -m venv .venv

echo "📥 Installing Python dependencies inside .venv..."
./.venv/bin/pip install -r python/requirements.txt

echo "🔨 Compiling Smart Contracts..."
npm run compile

echo "✅ Setup complete! You can now start the private chain."
echo "Use ./.venv/bin/python instead of python3 to run scripts."
