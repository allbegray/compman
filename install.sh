#!/usr/bin/env sh
# compman Linux/macOS One-Line Automatic Installer
set -e

# Pinned uv release (kept in sync with install.ps1): versioned download + official SHA256 verification.
UV_VERSION="0.12.5"
UV_BASE_URL="https://github.com/astral-sh/uv/releases/download/$UV_VERSION"
BIN_DIR="$HOME/.local/bin"
FISH_CONFIG="$HOME/.config/fish/config.fish"

fail() {
    echo "error: $1" >&2
    exit 1
}

echo "🚀 Installing compman CLI..."

if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv v$UV_VERSION (Python package manager)..."
    case "$(uname -s)-$(uname -m)" in
        Darwin-arm64)  uv_target="aarch64-apple-darwin" ;;
        Darwin-x86_64) uv_target="x86_64-apple-darwin" ;;
        Linux-x86_64)  uv_target="x86_64-unknown-linux-gnu" ;;
        Linux-aarch64) uv_target="aarch64-unknown-linux-gnu" ;;
        *) fail "unsupported platform '$(uname -s)-$(uname -m)': no prebuilt uv v$UV_VERSION asset" ;;
    esac
    asset="uv-$uv_target.tar.gz"
    tmp_dir="$(mktemp -d)"
    trap 'rm -rf "$tmp_dir"' EXIT
    curl -LsSfo "$tmp_dir/$asset" "$UV_BASE_URL/$asset"
    curl -LsSfo "$tmp_dir/$asset.sha256" "$UV_BASE_URL/$asset.sha256"
    if command -v sha256sum >/dev/null 2>&1; then
        (cd "$tmp_dir" && sha256sum -c "$asset.sha256") || fail "SHA256 mismatch: $asset"
    elif command -v shasum >/dev/null 2>&1; then
        (cd "$tmp_dir" && shasum -a 256 -c "$asset.sha256") || fail "SHA256 mismatch: $asset"
    else
        fail "no SHA256 tool found (need sha256sum or shasum)"
    fi
    mkdir -p "$BIN_DIR"
    tar -xzf "$tmp_dir/$asset" -C "$tmp_dir"
    mv "$tmp_dir/uv-$uv_target/uv" "$tmp_dir/uv-$uv_target/uvx" "$BIN_DIR/"
fi
uv tool install --force --reinstall --managed-python git+https://github.com/allbegray/compman.git

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        PROFILE=""
        if [ -n "$ZSH_VERSION" ] || [ -f "$HOME/.zshrc" ]; then
            PROFILE="$HOME/.zshrc"
        elif [ -f "$HOME/.bashrc" ]; then
            PROFILE="$HOME/.bashrc"
        elif [ -f "$FISH_CONFIG" ]; then
            PROFILE="$FISH_CONFIG"
        fi
        if [ -n "$PROFILE" ]; then
            case "$PROFILE" in
                "$FISH_CONFIG")
                    echo "fish_add_path -g \"$BIN_DIR\"" >> "$PROFILE"
                    ;;
                *)
                    echo "export PATH=\"$BIN_DIR:\$PATH\"" >> "$PROFILE"
                    ;;
            esac
            echo "✅ Automatically added $BIN_DIR to $PROFILE"
        fi
        export PATH="$BIN_DIR:$PATH"
        ;;
esac

if command -v compman >/dev/null 2>&1; then
    if [ -n "$ZSH_VERSION" ] || [ -f "$HOME/.zshrc" ]; then
        compman completion zsh --install >/dev/null 2>&1 || true
    elif [ -f "$HOME/.bashrc" ]; then
        compman completion bash --install >/dev/null 2>&1 || true
    elif command -v fish >/dev/null 2>&1 && [ -f "$FISH_CONFIG" ]; then
        fish -c "compman completion fish --install" >/dev/null 2>&1 || true
    fi
fi
printf "\n🎉 compman installed successfully! Run 'compman --help' to get started.\n"
