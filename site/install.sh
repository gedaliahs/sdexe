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

MIN_MINOR=11          # Python 3.11+
BREW_PY="python@3.12"
SDEXE_HOME="$HOME/.sdexe"
BIN_DIR="$HOME/.local/bin"
PLATFORM=""
# Logs live in our own folder: a fixed name in /tmp may belong to another user.
LOG_DIR="$SDEXE_HOME/logs"
NEW_SHELL=0           # 1 when PATH had to be changed, so open terminals are stale

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

# The file the user's shell reads when a new terminal window opens.
shell_profile() {
    # bash fills in SHELL from the login shell when the environment lacks it.
    case "$(basename "${SHELL:-sh}")" in
        zsh)
            # Terminal on macOS starts login shells; Linux terminals do not.
            if [ "$PLATFORM" = mac ]; then echo "${ZDOTDIR:-$HOME}/.zprofile"
            else echo "${ZDOTDIR:-$HOME}/.zshrc"; fi ;;
        bash)
            # A login bash reads only the first of these that exists, so never
            # create .bash_profile in front of an existing .profile.
            if [ "$PLATFORM" = linux ]; then echo "$HOME/.bashrc"
            elif [ -f "$HOME/.bash_profile" ]; then echo "$HOME/.bash_profile"
            elif [ -f "$HOME/.bash_login" ]; then echo "$HOME/.bash_login"
            elif [ -f "$HOME/.profile" ]; then echo "$HOME/.profile"
            else echo "$HOME/.bash_profile"; fi ;;
        fish) echo "${XDG_CONFIG_HOME:-$HOME/.config}/fish/conf.d/sdexe.fish" ;;
        *)    echo "$HOME/.profile" ;;
    esac
}

# ── python detection ──────────────────────────────────────────────────────────
py_ok() {
    # $1 = python executable. True if it is CPython >= 3.MIN_MINOR.
    # On a Mac without the Command Line Tools, /usr/bin/python3 is a placeholder
    # that opens an "install developer tools" dialog when run. Leave it alone.
    if [ "$PLATFORM" = mac ] && [ "$(command -v "$1" 2>/dev/null)" = /usr/bin/python3 ] \
        && ! xcode-select -p > /dev/null 2>&1; then
        return 1
    fi
    "$1" -c "import sys; sys.exit(0 if sys.version_info >= (3, $MIN_MINOR) else 1)" > /dev/null 2>&1
}
find_python() {
    local c
    for c in python3.14 python3.13 python3.12 python3.11 python3 python; do
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

no_brew() {
    # no_brew <required> <message> <hint>: the end of the install when Homebrew
    # is required, a warning when it is not.
    if [ "$1" = 1 ]; then fail "$2" "$3"; fi
    warn "$2"
    info "Continuing without Homebrew."
}

ensure_brew() {
    # ensure_brew <required>. Homebrew is required to install Python. When
    # Python is already here it is only wanted for ffmpeg, and sdexe has a
    # bundled ffmpeg to fall back on, so then a failure is not fatal.
    local required="${1:-1}"
    load_brew
    if have brew; then ok "Homebrew $(brew --version 2>/dev/null | head -1 | awk '{print $2}')"; return 0; fi
    if [ -z "$TTY" ]; then
        no_brew "$required" "Homebrew is missing and this shell has no terminal to ask for your password." \
            "Install it from https://brew.sh, then run this installer again."
        return 1
    fi
    info "Homebrew is not installed. Installing it now (this is the official installer from brew.sh)."
    local brew_installer=""
    brew_installer="$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || brew_installer=""
    if [ -z "$brew_installer" ]; then
        no_brew "$required" "Could not download the Homebrew installer." \
            "Check your internet connection, then run this installer again."
        return 1
    fi
    # Homebrew's non-interactive mode checks sudo with -n, which never prompts,
    # so ask for the password ourselves first and let it find the cached auth.
    printf '    Enter your Mac login password so Homebrew can install (nothing shows as you type).\n'
    if ! run_tty sudo -v; then
        no_brew "$required" "Could not get admin access." \
            "Your account must be an Administrator (System Settings -> Users & Groups)."
        return 1
    fi
    if ! NONINTERACTIVE=1 run_tty /bin/bash -c "$brew_installer"; then
        no_brew "$required" "Homebrew did not install." "Try again, or install it by hand from https://brew.sh"
        return 1
    fi
    load_brew
    if ! have brew; then
        no_brew "$required" "Homebrew installed but could not be found on PATH." \
            "Open a new Terminal window and run this installer again."
        return 1
    fi
    # Make brew available in future shells. The Homebrew installer prints this
    # advice but does not apply it.
    local shellenv_line profile
    shellenv_line="eval \"\$($(command -v brew) shellenv)\""
    profile="$(shell_profile)"
    case "$profile" in *.fish) profile="$HOME/.profile" ;; esac
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
    if HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_CLEANUP=1 run_tty brew install "$1" > "$LOG_DIR/brew.log" 2>&1; then
        ok "$2 installed"
    else
        return 1
    fi
}

install_mac() {
    step "Checking Homebrew"
    load_brew
    if have brew || ! find_python > /dev/null; then ensure_brew 1
    elif have ffmpeg; then info "Not needed: Python and ffmpeg are already installed."
    else ensure_brew 0 || true
    fi

    step "Checking Python"
    if PY="$(find_python)"; then
        ok "Python $("$PY" -c 'import sys;print(".".join(map(str,sys.version_info[:3])))') at $PY"
    else
        info "No Python 3.$MIN_MINOR+ found (macOS ships an older one)."
        brew_install "$BREW_PY" "Python 3.12" || fail "Python did not install." "See $LOG_DIR/brew.log"
        PY="$(find_python)" || fail "Python installed but could not be found."
        ok "Python $("$PY" -c 'import sys;print(".".join(map(str,sys.version_info[:3])))')"
    fi

    step "Checking ffmpeg"
    if have ffmpeg; then ok "ffmpeg already installed"
    elif have brew; then
        info "ffmpeg handles audio and video conversion. This can take a few minutes."
        brew_install ffmpeg ffmpeg || warn "ffmpeg did not install. sdexe will use its bundled copy instead."
    else
        warn "ffmpeg not found. sdexe will use its bundled copy instead."
    fi
}

# ── Linux ─────────────────────────────────────────────────────────────────────
SUDO=""
SUDO_NOTED=0
APT_REFRESHED=0
PKG_WHY=""
need_sudo() {
    # True when packages can be installed: we are root, or sudo exists.
    if [ "$(id -u)" = "0" ]; then SUDO=""; return 0; fi
    have sudo || return 1
    SUDO="sudo"
    if [ -z "$TTY" ] && [ "$SUDO_NOTED" = 0 ]; then
        info "sudo may need your password; run this from a terminal if it fails."
    fi
    SUDO_NOTED=1
}
pkg_install() {
    # pkg_install <label> <pkgs...>. Root is asked for only here, so a machine
    # that already has everything installs without it. On failure PKG_WHY says why.
    local label="$1"; shift
    if ! need_sudo; then
        PKG_WHY="Installing packages needs root, and sudo is not available. Install $* as root, then re-run."
        return 1
    fi
    PKG_WHY="See $LOG_DIR/pkg.log"
    if [ "$PKG" = apt ] && [ "$APT_REFRESHED" = 0 ]; then
        APT_REFRESHED=1
        info "Refreshing package lists..."
        run_tty $SUDO apt-get update > "$LOG_DIR/pkg.log" 2>&1 || warn "apt-get update failed, continuing with cached lists."
    fi
    info "Installing $label ($*)..."
    if run_tty $SUDO "${PKG_CMD[@]}" "$@" > "$LOG_DIR/pkg.log" 2>&1; then ok "$label installed"; return 0; fi
    return 1
}

install_linux() {
    step "Checking package manager"
    if have apt-get; then
        # noninteractive: a package question (tzdata's time zone) would wait
        # for an answer nobody can see, because output goes to the log.
        PKG=apt; PKG_CMD=(env DEBIAN_FRONTEND=noninteractive apt-get install -y)
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
    if [ -n "$PKG" ]; then ok "Using $PKG"; fi

    step "Checking Python"
    if PY="$(find_python)"; then
        ok "Python $("$PY" -c 'import sys;print(".".join(map(str,sys.version_info[:3])))') at $PY"
    else
        [ -n "$PKG" ] || fail "Python 3.$MIN_MINOR+ is required." "Install it with your package manager, then re-run."
        pkg_install "Python" "${PY_PKGS[@]}" || fail "Python did not install." "$PKG_WHY"
        # Ubuntu 22.04 and RHEL 9 have a newer Python next to an old default.
        local v
        for v in 3.13 3.12 3.11; do
            if find_python > /dev/null; then break; fi
            case "$PKG" in
                apt|dnf) pkg_install "Python $v" "python$v" || true ;;
                zypper)  pkg_install "Python $v" "python${v/./}" || true ;;
            esac
        done
        PY="$(find_python)" || fail "Your distribution's Python is older than 3.$MIN_MINOR." \
            "Install a newer Python (for example via https://github.com/pyenv/pyenv), then re-run."
    fi

    # Debian/Ubuntu keep the part of venv that installs pip (ensurepip) in a
    # separate package. `python3 -m venv --help` works without it, so test the
    # module itself. The package is named after the Python version.
    if [ "$PKG" = apt ] && ! "$PY" -c "import ensurepip" > /dev/null 2>&1; then
        local pyver
        pyver="$("$PY" -c 'import sys;print("%d.%d" % sys.version_info[:2])')"
        pkg_install "python3-venv" "python$pyver-venv" || pkg_install "python3-venv" python3-venv \
            || warn "python3-venv did not install; the next step may fail."
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

    # An environment without a working pip (a setup that was interrupted, or
    # Debian without python3-venv) can never be upgraded, so build it again.
    if [ -x "$vpy" ] && py_ok "$vpy" && "$vpy" -m pip --version > /dev/null 2>&1; then
        info "Found existing install at $SDEXE_HOME, upgrading..."
    else
        rm -rf "$venv"
        info "Creating a private Python environment at $SDEXE_HOME..."
        if ! "$PY" -m venv "$venv" > "$LOG_DIR/venv.log" 2>&1; then
            rm -rf "$venv"
            fail "Could not create the environment." "See $LOG_DIR/venv.log"
        fi
    fi
    "$vpy" -m pip install --quiet --upgrade pip > /dev/null 2>&1 || true
    info "Downloading sdexe and its dependencies from PyPI..."
    "$vpy" -m pip install --quiet --upgrade sdexe yt-dlp > "$LOG_DIR/pip.log" 2>&1 \
        || fail "sdexe did not install." "See $LOG_DIR/pip.log"

    # The sdexe a terminal finds today, before this one is linked in.
    local shadow=""
    shadow="$(command -v sdexe 2>/dev/null)" || shadow=""

    # Expose the command. Replace whatever is there (an older link, a pipx link).
    ln -sf "$venv/bin/sdexe" "$BIN_DIR/sdexe"
    ok "sdexe $("$venv/bin/sdexe" --version 2>/dev/null | awk '{print $2}') installed"

    # Make ~/.local/bin reachable in future shells.
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *)
            NEW_SHELL=1
            local profile
            profile="$(shell_profile)"
            if ! grep -qs '.local/bin' "$profile" 2>/dev/null; then
                mkdir -p "$(dirname "$profile")"
                case "$profile" in
                    *.fish) printf '# sdexe (added by the sdexe installer)\ncontains -- "$HOME/.local/bin" $PATH; or set -gx PATH "$HOME/.local/bin" $PATH\n' >> "$profile" ;;
                    *)      printf '\n# sdexe (added by the sdexe installer)\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$profile" ;;
                esac
                info "Added $BIN_DIR to PATH in $profile"
            fi
            ;;
    esac
    export PATH="$BIN_DIR:$PATH"

    # An earlier copy (pip install, pipx with its own bin folder) that sits
    # ahead on PATH would keep running instead of this one. When PATH was only
    # just changed, our folder goes in front, so there is nothing to warn about.
    if [ "$NEW_SHELL" = 0 ] && [ -n "$shadow" ] && ! [ "$shadow" -ef "$BIN_DIR/sdexe" ]; then
        warn "Another sdexe at $shadow comes first on your PATH and will run instead of this one."
        info "Remove it (pip uninstall sdexe, or pipx uninstall sdexe), then open a new terminal."
    fi
    if have pipx; then
        # Read the whole list first: grep -q in a pipe stops pipx early, and
        # pipefail then reports the match as a failure.
        local pipx_pkgs=""
        pipx_pkgs="$(pipx list --short 2>/dev/null)" || pipx_pkgs=""
        case $'\n'"$pipx_pkgs" in
            *$'\n'"sdexe "*) info "An older pipx copy of sdexe is no longer used. Remove it with: pipx uninstall sdexe" ;;
        esac
    fi

    printf '\n%s%s✓ Done.%s Update any time with %ssdexe update%s\n' "$BOLD" "$GREEN" "$RESET" "$BOLD" "$RESET"
}

launch() {
    printf '\nRun %ssdexe%s from any terminal to start it. It opens in your browser at http://localhost:5001\n' "$BOLD" "$RESET"
    [ -x "$BIN_DIR/sdexe" ] || return 0
    local ans="n"
    if [ -n "$TTY" ]; then
        printf '\n%sLaunch sdexe now? [Y/n]%s ' "$BOLD" "$RESET" > "$TTY"
        read -r ans < "$TTY" || ans=""
    fi
    case "$ans" in
        n|N|no|NO) ;;
        # stdin is this script when it was piped from curl; sdexe needs the
        # terminal, or it starts without its setup questions and its app.
        *) printf '\n'; exec "$BIN_DIR/sdexe" < "$TTY" ;;
    esac
    if [ "$NEW_SHELL" = 1 ]; then
        printf '%sOpen a new terminal window first so the sdexe command is found.%s\n' "$DIM" "$RESET"
    fi
}

# ── go ────────────────────────────────────────────────────────────────────────
main() {
    local os
    os="$(uname -s)"
    case "$os" in
        Darwin) PLATFORM=mac ;;
        Linux)  PLATFORM=linux ;;
        *) fail "Unsupported system: $os" "On Windows, run in PowerShell:  irm https://sdexe.com/install.ps1 | iex" ;;
    esac

    printf '\n%s%ssdexe installer%s  %s(%s)%s\n' "$BOLD" "$BLUE" "$RESET" "$DIM" "$PLATFORM" "$RESET"
    printf '%sSuite for Downloading, Editing & eXporting Everything%s\n' "$DIM" "$RESET"

    mkdir -p "$LOG_DIR"
    case "$PLATFORM" in
        mac)   install_mac ;;
        linux) install_linux ;;
    esac
    install_sdexe
    launch
}

# Only settings and function definitions come before this. The install starts
# from this last line, so a download cut off part way does nothing at all.
main
