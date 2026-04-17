#!/usr/bin/env bash
set -e

REPO="Murhaf-Mo/moodlectl"

echo ""
echo "moodlectl installer"
echo "==================="
echo ""

# ── 1. Homebrew (macOS only) ─────────────────────────────────────────────────
if [[ "$OSTYPE" == "darwin"* ]]; then
    if ! command -v brew &>/dev/null; then
        echo "Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        # Add brew to PATH for Apple Silicon
        if [[ -f "/opt/homebrew/bin/brew" ]]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        fi
    fi
fi

# ── 2. Python 3.12+ ──────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null || ! python3 -c "import sys; assert sys.version_info >= (3,12)" &>/dev/null; then
    echo "Installing Python 3.12..."
    if command -v brew &>/dev/null; then
        brew install python@3.12
    else
        echo "Error: Python 3.12+ is required. Install it from https://python.org and re-run."
        exit 1
    fi
fi

PYTHON=$(command -v python3.12 || command -v python3)

# ── 3. pipx ──────────────────────────────────────────────────────────────────
if ! command -v pipx &>/dev/null; then
    echo "Installing pipx..."
    if command -v brew &>/dev/null; then
        brew install pipx
    else
        "$PYTHON" -m pip install --user pipx
    fi
    "$PYTHON" -m pipx ensurepath
fi

# ── 4. moodlectl ─────────────────────────────────────────────────────────────
echo "Installing moodlectl..."
pipx install --force "git+https://github.com/$REPO"

echo "Installing browser support (for auth login)..."
pipx inject --force moodlectl selenium webdriver-manager

echo "Installing analytics support..."
pipx inject --force moodlectl plotext matplotlib

echo ""
echo "moodlectl installed successfully!"
echo ""
echo "Next steps:"
echo "  1. Open a NEW terminal window (so PATH is refreshed)"
echo "  2. Run: moodlectl auth login"
echo "     Chrome will open — log in with your CCK credentials."
echo "     The window closes automatically when done."
echo ""
echo "Then try: moodlectl --help"
