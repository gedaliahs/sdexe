#!/bin/bash
# sdexe installer for macOS and Linux.
#
#   curl -fsSL https://sdexe.com/install.sh | bash
#
# Installs everything sdexe needs on a fresh machine, in order:
#   macOS:  Homebrew (if missing) -> Python 3.12 -> ffmpeg -> sdexe
#   Linux:  python3 + ffmpeg via apt/dnf/pacman/zypper -> sdexe
# sdexe lives in its own private environment at ~/.sdexe and is linked into
# ~/.local/bin, so nothing else on the system is touched.
# Safe to re-run: existing pieces are skipped, sdexe is upgraded.
# Later, `sdexe update` upgrades it in place.

set -euo pipefail

MIN_MINOR=10          # Python 3.10+
BREW_PY="python@3.12"
SDEXE_HOME="$HOME/.sdexe"
BIN_DIR="$HOME/.local/bin"

# ── output helpers ────────────────────────────────────────────────────────────
if [ -t 1 ] && [ "${TERM:-dumb}" != "dumb" ]; then
    BOLD=$'\033[1m'; DIM=$'\033[2m'; BLUE=$'\033[34m'; GREEN=$'\033[32m'
    YELLOW=$'\033[33m'; RED=$'\033[31m'; RESET=$'\033[0m'
else
    BOLD=""; DIM=""; BLUE=""; GREEN=""; YELLOW=""; RED=""; RESET=""
fi
STEP=0
step() { STEP=$((STEP + 1)); printf '\n%s%s[%d]%s %s%s%s\n' "$BOLD" "$BLUE" "$STEP" "$RESET" "$BOLD" "$1" "$RESET"; }
ok()   { printf '    %s✓%s %s\n' "$GREEN" "$RESET" "$1"; }
info() { printf '    %s%s%s\n' "$DIM" "$1" "$RESET"; }
warn() { printf '    %s!%s %s\n' "$YELLOW" "$RESET" "$1"; }
fail() { printf '\n%s✗ %s%s\n' "$RED" "$1" "$RESET" >&2; [ -n "${2:-}" ] && printf '  %s\n' "$2" >&2; exit 1; }

# Commands that may prompt (sudo, Homebrew) need a real terminal even when this
# script arrives through a pipe.
TTY=""
if ( : < /dev/tty ) 2> /dev/null && ( : > /dev/tty ) 2> /dev/null; then TTY=/dev/tty; fi
run_tty() { if [ -n "$TTY" ]; then "$@" < "$TTY"; else "$@" < /dev/null; fi; }

have() { command -v "$1" > /dev/null 2>&1; }

# ── detect platform ───────────────────────────────────────────────────────────
OS="$(uname -s)"
case "$OS" in
    Darwin) PLATFORM=mac ;;
    Linux)  PLATFORM=linux ;;
    *) fail "Unsupported system: $OS" "On Windows, run in PowerShell:  irm https://sdexe.com/install.ps1 | iex" ;;
esac

printf '\n%s%ssdexe installer%s  %s(%s)%s\n' "$BOLD" "$BLUE" "$RESET" "$DIM" "$PLATFORM" "$RESET"
printf '%sSuite for Downloading, Editing & eXporting Everything%s\n' "$DIM" "$RESET"

# ── python detection ──────────────────────────────────────────────────────────
py_ok() {
    # $1 = python executable. True if it is CPython >= 3.MIN_MINOR.
    "$1" -c "import sys; sys.exit(0 if sys.version_info >= (3, $MIN_MINOR) else 1)" > /dev/null 2>&1
}
find_python() {
    local c
    for c in python3.14 python3.13 python3.12 python3.11 python3.10 python3 python; do
        if have "$c" && py_ok "$c"; then command -v "$c"; return 0; fi
    done
    # Homebrew keg-only pythons that are not on PATH yet
    for c in /opt/homebrew/opt/$BREW_PY/bin/python3 /usr/local/opt/$BREW_PY/bin/python3 \
             /opt/homebrew/bin/python3 /usr/local/bin/python3; do
        if [ -x "$c" ] && py_ok "$c"; then echo "$c"; return 0; fi
    done
    return 1
}

# ── macOS ─────────────────────────────────────────────────────────────────────
load_brew() {
    if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [ -x /usr/local/bin/brew ]; then eval "$(/usr/local/bin/brew shellenv)"
    fi
}

ensure_brew() {
    load_brew
    if have brew; then ok "Homebrew $(brew --version 2>/dev/null | head -1 | awk '{print $2}')"; return; fi
    [ -n "$TTY" ] || fail "Homebrew is missing and this shell has no terminal to ask for your password." \
        "Install it from https://brew.sh, then run this installer again."
    info "Homebrew is not installed. Installing it now (this is the official installer from brew.sh)."
    # Homebrew's non-interactive mode checks sudo with -n, which never prompts,
    # so ask for the password ourselves first and let it find the cached auth.
    printf '    Enter your Mac login password so Homebrew can install (nothing shows as you type).\n'
    run_tty sudo -v || fail "Could not get admin access." \
        "Your account must be an Administrator (System Settings -> Users & Groups)."
    NONINTERACTIVE=1 run_tty /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
        || fail "Homebrew did not install." "Try again, or install it by hand from https://brew.sh"
    load_brew
    have brew || fail "Homebrew installed but could not be found on PATH." "Open a new Terminal window and run this installer again."
    # Make brew available in future shells. The Homebrew installer prints this
    # advice but does not apply it.
    local shellenv_line profile
    shellenv_line="eval \"\$($(command -v brew) shellenv)\""
    case "$(basename "${SHELL:-/bin/zsh}")" in
        zsh)  profile="$HOME/.zprofile" ;;
        bash) profile="$HOME/.bash_profile" ;;
        *)    profile="$HOME/.profile" ;;
    esac
    if ! grep -qs 'brew shellenv' "$profile" 2>/dev/null; then
        printf '\n# Homebrew (added by the sdexe installer)\n%s\n' "$shellenv_line" >> "$profile"
        info "Added Homebrew to $profile"
    fi
    ok "Homebrew installed"
}

brew_install() {
    # brew_install <formula> <label>
    if brew list --formula "$1" > /dev/null 2>&1; then ok "$2 already installed"; return 0; fi
    info "Installing $2 with Homebrew..."
    if HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_CLEANUP=1 run_tty brew install "$1" > /tmp/sdexe-brew.log 2>&1; then
        ok "$2 installed"
    else
        return 1
    fi
}

install_mac() {
    step "Checking Homebrew"
    ensure_brew

    step "Checking Python"
    if PY="$(find_python)"; then
        ok "Python $("$PY" -c 'import sys;print(".".join(map(str,sys.version_info[:3])))') at $PY"
    else
        info "No Python 3.$MIN_MINOR+ found (macOS ships an older one)."
        brew_install "$BREW_PY" "Python 3.12" || fail "Python did not install." "See /tmp/sdexe-brew.log"
        PY="$(find_python)" || fail "Python installed but could not be found."
        ok "Python $("$PY" -c 'import sys;print(".".join(map(str,sys.version_info[:3])))')"
    fi

    step "Checking ffmpeg"
    if have ffmpeg; then ok "ffmpeg already installed"
    else
        info "ffmpeg handles audio and video conversion. This can take a few minutes."
        brew_install ffmpeg ffmpeg || warn "ffmpeg did not install. sdexe will use its bundled copy instead."
    fi
}

# ── Linux ─────────────────────────────────────────────────────────────────────
SUDO=""
need_sudo() {
    if [ "$(id -u)" = "0" ]; then SUDO=""; return; fi
    have sudo || fail "This needs root to install packages, and sudo is not available." \
        "Install python3 (3.$MIN_MINOR+) and ffmpeg with your package manager, then re-run."
    SUDO="sudo"
    [ -n "$TTY" ] || info "sudo may need your password; run this from a terminal if it fails."
}
pkg_install() {
    # pkg_install <label> <pkgs...>
    local label="$1"; shift
    info "Installing $label ($*)..."
    run_tty $SUDO "${PKG_CMD[@]}" "$@" > /tmp/sdexe-pkg.log 2>&1 && ok "$label installed" && return 0
    return 1
}

install_linux() {
    step "Checking package manager"
    if have apt-get; then
        PKG=apt; PKG_CMD=(apt-get install -y)
        PY_PKGS=(python3 python3-venv python3-pip); FF_PKG=ffmpeg
    elif have dnf; then
        PKG=dnf; PKG_CMD=(dnf install -y)
        PY_PKGS=(python3 python3-pip); FF_PKG=ffmpeg-free
    elif have pacman; then
        PKG=pacman; PKG_CMD=(pacman -S --noconfirm --needed)
        PY_PKGS=(python python-pip); FF_PKG=ffmpeg
    elif have zypper; then
        PKG=zypper; PKG_CMD=(zypper install -y)
        PY_PKGS=(python3 python3-pip); FF_PKG=ffmpeg
    else
        PKG=""; warn "No supported package manager found (apt, dnf, pacman, zypper)."
    fi
    [ -n "$PKG" ] && ok "Using $PKG"
    need_sudo
    if [ "$PKG" = apt ]; then
        info "Refreshing package lists..."
        run_tty $SUDO apt-get update > /tmp/sdexe-pkg.log 2>&1 || warn "apt-get update failed, continuing with cached lists."
    fi

    step "Checking Python"
    if PY="$(find_python)"; then
        ok "Python $("$PY" -c 'import sys;print(".".join(map(str,sys.version_info[:3])))') at $PY"
    else
        [ -n "$PKG" ] || fail "Python 3.$MIN_MINOR+ is required." "Install it with your package manager, then re-run."
        pkg_install "Python" "${PY_PKGS[@]}" || fail "Python did not install." "See /tmp/sdexe-pkg.log"
        PY="$(find_python)" || fail "Your distribution's Python is older than 3.$MIN_MINOR." \
            "Install a newer Python (for example via https://github.com/pyenv/pyenv), then re-run."
    fi

    # Debian/Ubuntu split venv out of python3; make sure it is there.
    if [ "$PKG" = apt ] && ! "$PY" -m venv --help > /dev/null 2>&1; then
        pkg_install "python3-venv" python3-venv || warn "python3-venv did not install; the next step may fail."
    fi

    step "Checking ffmpeg"
    if have ffmpeg; then ok "ffmpeg already installed"
    elif [ -n "$PKG" ]; then
        pkg_install "ffmpeg" "$FF_PKG" || warn "ffmpeg did not install. sdexe will use its bundled copy instead."
    else
        warn "ffmpeg not found. sdexe will use its bundled copy instead."
    fi
}

# ── shared: install sdexe into its own private environment ────────────────────
install_sdexe() {
    step "Installing sdexe"
    local venv="$SDEXE_HOME/venv" vpy="$SDEXE_HOME/venv/bin/python"
    mkdir -p "$SDEXE_HOME" "$BIN_DIR"

    if [ -x "$vpy" ] && "$vpy" -c "import sys; sys.exit(0 if sys.version_info >= (3, $MIN_MINOR) else 1)" 2>/dev/null; then
        info "Found existing install at $SDEXE_HOME, upgrading..."
    else
        [ -d "$venv" ] && rm -rf "$venv"
        info "Creating a private Python environment at $SDEXE_HOME..."
        "$PY" -m venv "$venv" > /tmp/sdexe-venv.log 2>&1 \
            || fail "Could not create the environment." "See /tmp/sdexe-venv.log"
    fi
    "$vpy" -m pip install --quiet --upgrade pip > /dev/null 2>&1 || true
    info "Downloading sdexe and its dependencies from PyPI..."
    "$vpy" -m pip install --quiet --upgrade sdexe yt-dlp > /tmp/sdexe-pip.log 2>&1 \
        || fail "sdexe did not install." "See /tmp/sdexe-pip.log"

    # Expose the command. Replace whatever is there (an older link, a pipx link).
    ln -sf "$venv/bin/sdexe" "$BIN_DIR/sdexe"
    ok "sdexe $("$venv/bin/sdexe" --version 2>/dev/null | awk '{print $2}') installed"

    # Make ~/.local/bin reachable in future shells.
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *)
            local profile
            case "$(basename "${SHELL:-/bin/zsh}")" in
                zsh)  profile="$HOME/.zprofile" ;;
                bash) profile="$HOME/.bash_profile"; [ "$PLATFORM" = linux ] && profile="$HOME/.bashrc" ;;
                *)    profile="$HOME/.profile" ;;
            esac
            if ! grep -qs '.local/bin' "$profile" 2>/dev/null; then
                printf '\n# sdexe (added by the sdexe installer)\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$profile"
                info "Added $BIN_DIR to PATH in $profile"
            fi
            ;;
    esac
    export PATH="$BIN_DIR:$PATH"

    if have pipx && pipx list --short 2>/dev/null | grep -q '^sdexe '; then
        info "An older pipx copy of sdexe is no longer used. Remove it with: pipx uninstall sdexe"
    fi

    printf '\n%s%s✓ Done.%s Update any time with %ssdexe update%s\n' "$BOLD" "$GREEN" "$RESET" "$BOLD" "$RESET"
}

launch() {
    printf '\nRun %ssdexe%s from any terminal to start it. It opens in your browser at http://localhost:5001\n' "$BOLD" "$RESET"
    [ -x "$BIN_DIR/sdexe" ] || return 0
    if [ -n "$TTY" ]; then
        printf '\n%sLaunch sdexe now? [Y/n]%s ' "$BOLD" "$RESET" > "$TTY"
        local ans=""
        read -r ans < "$TTY" || ans=""
        case "$ans" in
            n|N|no|NO) printf '%sOpen a new terminal window first so the sdexe command is found.%s\n' "$DIM" "$RESET" ;;
            *) printf '\n'; exec "$BIN_DIR/sdexe" ;;
        esac
    else
        printf '%sOpen a new terminal window first so the sdexe command is found.%s\n' "$DIM" "$RESET"
    fi
}

# ── go ────────────────────────────────────────────────────────────────────────
have curl || fail "curl is required." "Install curl, then run this again."
case "$PLATFORM" in
    mac)   install_mac ;;
    linux) install_linux ;;
esac
install_sdexe
launch
