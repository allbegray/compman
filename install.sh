#!/usr/bin/env sh
# compman Linux/macOS One-Line Automatic Installer
set -e

echo "🚀 Installing compman CLI..."

if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv (Python package manager)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
uv tool install --force --reinstall --managed-python git+https://github.com/allbegray/compman.git

BIN_DIR="$HOME/.local/bin"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        PROFILE=""
        FISH_CONFIG="$HOME/.config/fish/config.fish"
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
