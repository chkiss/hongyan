#!/bin/bash
# Set up the REVIEW HOST of a two-device install. Standalone: no clone needed.
#
#   curl -fsSL https://raw.githubusercontent.com/chkiss/hongyan/main/install-review-host.sh | bash
#
# The review host does not run the assistant. It reaches the server over SSH
# once a month, reads the log and config, and messages you through the server.
# So it needs no signal-cli, no API key and no config of its own — only SSH
# access and the brief this script writes.
#
# Piping a script from the internet into a shell deserves suspicion, so: this
# one writes exactly two things, both under ~/.config/hongyan, and the only
# machine it modifies besides this one is the server you name, where it sets
# monthly_review to "remote" and removes the server's own monthly cron line.
# Read it first if you would rather; it is short.

set -uo pipefail

BRIEF_URL="${HONGYAN_BRIEF_URL:-https://raw.githubusercontent.com/chkiss/hongyan/main/docs/monthly-review-brief.md}"
DEST="$HOME/.config/hongyan"
BRIEF="$DEST/monthly-review-brief.md"

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
ok()   { printf '  \033[32mok\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

say "hongyan — review host setup"
info "This machine will audit a hongyan server once a month."
info "It needs SSH access to that server. Nothing else."

# Piped into a shell, stdin is the script itself, so a prompt would read the
# script's own text. Take input from the terminal instead — or from
# HONGYAN_TARGET, which also makes the script usable unattended.
TARGET="${HONGYAN_TARGET:-}"
if [ -z "$TARGET" ]; then
    if [ ! -t 0 ] && [ -e /dev/tty ]; then
        exec < /dev/tty
    fi
    if [ ! -t 0 ]; then
        die "No terminal for prompts. Either run the script directly, or set
the target up front:
    HONGYAN_TARGET=user@host bash install-review-host.sh"
    fi
    printf '\n'
    read -r -p "  SSH target for the server (user@host): " TARGET
fi
[ -n "$TARGET" ] || die "An SSH target is required."

say "Testing SSH"
info "Connecting to $TARGET ..."
if ! ssh -o ConnectTimeout=10 -o BatchMode=yes "$TARGET" 'echo hongyan-ssh-ok' 2>/dev/null | grep -q hongyan-ssh-ok; then
    die "Could not reach $TARGET without a password.
Set up key-based SSH first:
    ssh-copy-id $TARGET
then run this again."
fi
ok "reached $TARGET and ran a command there"

say "Checking it is actually a hongyan server"
if ssh -o BatchMode=yes "$TARGET" 'test -f ~/.config/hongyan/config.json' 2>/dev/null; then
    ok "found ~/.config/hongyan/config.json"
else
    warn "No hongyan config found at ~/.config/hongyan/config.json on $TARGET."
    warn "Install the server side there first, or check the target."
    read -r -p "  Continue anyway? [y/N]: " reply
    case "$reply" in [yY]*) ;; *) die "Stopped." ;; esac
fi

say "Handing the monthly review to this machine"
if ssh -o BatchMode=yes "$TARGET" 'python3 - <<PY
import json, os
p = os.path.expanduser("~/.config/hongyan/config.json")
try:
    c = json.load(open(p))
except Exception as e:
    raise SystemExit("config unreadable: %s" % e)
c["monthly_review"] = "remote"
json.dump(c, open(p, "w"), indent=2, ensure_ascii=False)
print("ok")
PY' 2>/dev/null | grep -q ok; then
    ok "server set to monthly_review = remote"
else
    warn "Could not update the server config. Set monthly_review to \"remote\" there"
    warn "by hand, or you will get two monthly reports that disagree."
fi

if ssh -o BatchMode=yes "$TARGET" 'crontab -l 2>/dev/null | grep -q -- "--monthly"' 2>/dev/null; then
    ssh -o BatchMode=yes "$TARGET" 'crontab -l 2>/dev/null | grep -v -- "--monthly" > /tmp/hongyan.cron && crontab /tmp/hongyan.cron && rm -f /tmp/hongyan.cron' 2>/dev/null \
        && ok "removed the server's own monthly cron line" \
        || warn "could not edit the server crontab; remove the --monthly line by hand"
else
    ok "server has no monthly cron line to remove"
fi

say "Fetching the review brief"
mkdir -p "$DEST"
if command -v curl >/dev/null; then
    curl -fsSL "$BRIEF_URL" -o "$BRIEF" || die "Could not download the brief from $BRIEF_URL"
elif command -v wget >/dev/null; then
    wget -qO "$BRIEF" "$BRIEF_URL" || die "Could not download the brief from $BRIEF_URL"
else
    die "Need curl or wget to fetch the brief."
fi
# The brief refers to the server generically; make it concrete.
sed -i "s|SSH_TARGET|$TARGET|g" "$BRIEF" 2>/dev/null || true
ok "wrote $BRIEF"

say "Done"
info "Register this with your agent runner on a monthly schedule:"
info "  $BRIEF"
info ""
info "It is written for an agent that can read files over SSH and run commands."
info "Everything in it is read-only until you reply 'approve' over Signal."
