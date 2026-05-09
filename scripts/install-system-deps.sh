#!/usr/bin/env sh
set -eu

DRY_RUN=0
REQUIRE_TARGET="cli"

usage() {
  cat <<'USAGE'
Usage:
  scripts/install-system-deps.sh [--dry-run] [--require cli|desktop-gui|web-gui|dev]

Installs operating-system packages needed by GuildBridge on supported Linux,
BSD, macOS, and Termux/Android environments. Use --dry-run to print the
package-manager commands without executing them.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      ;;
    --require)
      shift
      if [ "$#" -eq 0 ]; then
        echo "--require needs a value." >&2
        exit 2
      fi
      REQUIRE_TARGET="$1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

case "$REQUIRE_TARGET" in
  cli|desktop-gui|web-gui|dev) ;;
  *)
    echo "Unknown --require target: $REQUIRE_TARGET" >&2
    exit 2
    ;;
esac

need_sudo() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf ''
    return
  fi
  if [ "$(id -u)" -eq 0 ]; then
    printf ''
  elif command -v sudo >/dev/null 2>&1; then
    printf 'sudo'
  elif [ -n "${TERMUX_VERSION:-}" ]; then
    printf ''
  else
    echo "Run as root or install sudo." >&2
    exit 1
  fi
}

SUDO="$(need_sudo)"

run() {
  echo "+ $*"
  if [ "$DRY_RUN" -eq 1 ]; then
    return 0
  fi
  "$@"
}

run_with_sudo() {
  if [ -n "$SUDO" ]; then
    run "$SUDO" "$@"
  else
    run "$@"
  fi
}

if [ -n "${GUILDBRIDGE_UNAME_S:-}" ]; then
  UNAME_S="$GUILDBRIDGE_UNAME_S"
else
  UNAME_S="$(uname -s)"
fi

python_command() {
  if command -v python3 >/dev/null 2>&1; then
    printf 'python3'
  elif command -v python >/dev/null 2>&1; then
    printf 'python'
  else
    printf 'python3'
  fi
}

run_platform_check() {
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "+ $(python_command) scripts/check-platform.py --require $REQUIRE_TARGET"
    return 0
  fi
  "$(python_command)" scripts/check-platform.py --require "$REQUIRE_TARGET"
}

if [ -n "${TERMUX_VERSION:-}" ] || [ -n "${ANDROID_ROOT:-}" ]; then
  run pkg update
  run pkg install -y python git ca-certificates
  run_platform_check
  exit 0
fi

case "$UNAME_S" in
  Darwin)
    if command -v brew >/dev/null 2>&1; then
      run brew install python git
    elif command -v port >/dev/null 2>&1; then
      run_with_sudo port install python312 py312-pip git
    else
      echo "Install Python 3.10+ from python.org, Homebrew, or MacPorts." >&2
      exit 1
    fi
    run_platform_check
    exit 0
    ;;
  FreeBSD)
    run_with_sudo pkg install -y python py312-pip py312-tkinter git ca_root_nss
    run_platform_check
    exit 0
    ;;
  NetBSD)
    if command -v pkgin >/dev/null 2>&1; then
      run_with_sudo pkgin -y install python312 py312-pip py312-tkinter git mozilla-rootcerts
    else
      run_with_sudo pkg_add python312 py312-pip py312-tkinter git mozilla-rootcerts
    fi
    run_platform_check
    exit 0
    ;;
  OpenBSD)
    run_with_sudo pkg_add -I python%3.12 py3-pip python-tkinter git
    run_platform_check
    exit 0
    ;;
esac

if [ -n "${GUILDBRIDGE_OS_RELEASE:-}" ] && [ -r "$GUILDBRIDGE_OS_RELEASE" ]; then
  # shellcheck disable=SC1090
  . "$GUILDBRIDGE_OS_RELEASE"
elif [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
else
  ID="$(printf '%s' "$UNAME_S" | tr '[:upper:]' '[:lower:]')"
  ID_LIKE=""
fi

ids=" ${ID:-} ${ID_LIKE:-} ${NAME:-} "

case "$ids" in
  *debian*|*ubuntu*|*linuxmint*|*mint*)
    run_with_sudo apt-get update
    run_with_sudo apt-get install -y python3 python3-pip python3-venv python3-tk git ca-certificates
    ;;
  *fedora*|*rhel*|*almalinux*|*rocky*|*oracle*|*centos*)
    if command -v dnf >/dev/null 2>&1; then
      run_with_sudo dnf install -y python3 python3-pip python3-tkinter git ca-certificates
    elif command -v yum >/dev/null 2>&1; then
      run_with_sudo yum install -y python3 python3-pip python3-tkinter git ca-certificates
    else
      echo "No dnf or yum found." >&2
      exit 1
    fi
    ;;
  *arch*|*manjaro*)
    run_with_sudo pacman -Sy --needed --noconfirm python python-pip tk git ca-certificates
    ;;
  *gentoo*)
    run_with_sudo emerge --ask=n dev-lang/python dev-python/pip dev-lang/tk dev-vcs/git app-misc/ca-certificates
    ;;
  *)
    echo "Unsupported or unknown Linux distribution: ${PRETTY_NAME:-$ID}" >&2
    exit 1
    ;;
esac

run_platform_check
