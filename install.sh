#!/bin/bash
# Bootstrap for hongyan: make sure the checkout exists, then hand over to
# hongyan-config, which detects installed state — a fresh machine gets the
# installer, an existing one gets the config menu. One tool, one entry point.

set -uo pipefail

CLONE_URL="${HONGYAN_REPO:-https://github.com/chkiss/hongyan}"
REPO="${HONGYAN_DIR:-$HOME/hongyan}"

# Piped from curl there is no checkout: fetch the code first.
if [ ! -f "$REPO/hongyan_listener.py" ]; then
    command -v git >/dev/null || { echo "git is required to install this way." >&2; exit 1; }
    if [ -d "$REPO/.git" ]; then
        printf '  Updating existing checkout at %s\n' "$REPO"
        git -C "$REPO" pull --quiet || printf '  (could not update; using what is there)\n'
    else
        printf '  Fetching hongyan into %s\n' "$REPO"
        git clone --quiet "$CLONE_URL" "$REPO" || { echo "Could not clone $CLONE_URL" >&2; exit 1; }
    fi
fi
[ -f "$REPO/hongyan_listener.py" ] || { echo "$REPO does not look like a hongyan checkout." >&2; exit 1; }

# Piped from curl, stdin is the script itself — take answers from the terminal.
if [ ! -t 0 ] && [ -e /dev/tty ]; then
    exec < /dev/tty
fi

# Git hooks are not versioned, so a fresh clone has none — which is the state
# in which a real ACI once reached a public commit. Install them before the
# config exists, so the guard predates the identity it guards.
[ -x "$REPO/scripts/install-hooks.sh" ] && \
    bash "$REPO/scripts/install-hooks.sh" >/dev/null 2>&1

exec python3 "$REPO/hongyan-config" --install
