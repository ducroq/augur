#!/usr/bin/env bash
# Shared Netlify build script — used by all build contexts in netlify.toml
set -euo pipefail

CONTEXT="${1:-production}"
HUGO_EXTRA_FLAGS="${2:-}"

echo "Building Augur ($CONTEXT)..."

echo "Installing Python dependencies..."
pip install cryptography

echo "Fetching and decrypting energy data (forcing fresh fetch)..."
mkdir -p static/data
python decrypt_data_cached.py --force

echo "Building Hugo site..."
if [ -n "$HUGO_EXTRA_FLAGS" ]; then
    hugo --minify $HUGO_EXTRA_FLAGS
else
    hugo --minify
fi

echo "Build complete ($CONTEXT)!"
