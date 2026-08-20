#!/bin/bash
# Interactive installer.
#
# Run it on each machine you want to set up and tell it what that machine is.
# There are two shapes:
#
#   One device   Everything runs on the server, including the monthly review.
#                Needs nothing but the server itself. This is the default and
#                what most people want.
#
#   Two devices  The server runs the assistant; a second machine runs a richer
#                monthly review with a full agent (more memory, better tooling,
#                and it can apply fixes rather than only describe them). The
#                review host reaches the server over SSH; the server never
#                needs to reach back.
#
# Nothing here is destructive: an existing config is never overwritten without
# asking, and cron lines are added only if an equivalent line is absent.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE="$HOME/.config/hongyan"
BIN="$HOME/.local/bin"
CONFIG="$STATE/config.json"

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
ok()   { printf '  \033[32mok\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

ask() {  # ask <prompt> <default>
    local prompt="$1" default="${2:-}" reply
    if [ -n "$default" ]; then
        read -r -p "  $prompt [$default]: " reply
        printf '%s' "${reply:-$default}"
    else
        read -r -p "  $prompt: " reply
        printf '%s' "$reply"
    fi
}

confirm() {  # confirm <prompt>  -> 0 for yes
    local reply
    read -r -p "  $1 [y/N]: " reply
    case "$reply" in [yY]*) return 0 ;; *) return 1 ;; esac
}

add_cron() {  # add_cron <schedule> <command> <comment>
    local schedule="$1" command="$2" comment="$3" current
    current="$(crontab -l 2>/dev/null)"
    if printf '%s' "$current" | grep -Fq -- "$command"; then
        info "cron already has: $command"
        return 0
    fi
    printf '%s\n# %s\n%s %s\n' "$current" "$comment" "$schedule" "$command" \
        | sed '/^$/d' | crontab -
    ok "cron: $schedule $command"
}

# ---------------------------------------------------------------- server ---

install_server() {
    local review_mode="$1"

    say "Checking prerequisites"
    command -v python3 >/dev/null || die "python3 not found."
    ok "python3 $(python3 -V 2>&1 | awk '{print $2}')"

    if [ -x "$BIN/signal-cli" ] || command -v signal-cli >/dev/null; then
        ok "signal-cli found"
    else
        warn "signal-cli not found in PATH or $BIN."
        warn "Install it from https://github.com/AsamK/signal-cli and register"
        warn "the BOT's own number (not your personal one) before starting."
    fi

    mkdir -p "$STATE" "$BIN"

    say "Configuration"
    if [ -f "$CONFIG" ]; then
        warn "$CONFIG already exists."
        if confirm "Keep it as is and skip configuration?"; then
            info "keeping existing config"
        else
            cp "$CONFIG" "$CONFIG.bak-$(date +%F-%H%M%S)"
            ok "backed up existing config"
            write_config "$review_mode"
        fi
    else
        write_config "$review_mode"
    fi

    say "Linking commands into $BIN"
    local f
    for f in hongyan_listener.py hongyan-supervise hongyan-watchdog hongyan-send.py hongyan-me; do
        [ -e "$REPO/$f" ] || continue
        if [ -e "$BIN/$f" ] && [ ! -L "$BIN/$f" ]; then
            mv "$BIN/$f" "$BIN/$f.pre-install"
            warn "moved existing $f to $f.pre-install"
        fi
        ln -sfn "$REPO/$f" "$BIN/$f"
        chmod +x "$REPO/$f"
    done
    ok "symlinked to the repository, so git pull updates the running system"

    say "Scheduling"
    add_cron "@reboot" "sleep 30 && $BIN/hongyan-supervise" "Start at boot"
    add_cron "*/10 * * * *" "$BIN/hongyan-watchdog --restart" "Quiet restart if it dies"
    add_cron "23 8 * * *" "$BIN/hongyan-watchdog --daily" "Daily health check + queue digest"
    if [ "$review_mode" = "local" ]; then
        add_cron "0 9 1 * *" "$BIN/hongyan-watchdog --monthly" "Monthly review"
    else
        info "monthly review runs on the other machine; no cron line added here"
    fi

    say "Tests"
    if python3 "$REPO/tests/test_listener.py" >/dev/null 2>&1; then
        ok "test suite passes"
    else
        warn "test suite failed — run 'python3 tests/test_listener.py' to see why"
    fi

    say "Done"
    info "Start it with:  $BIN/hongyan-supervise"
    info "Then text the bot 'status' from the phone whose ACI you configured."
}

write_config() {
    local review_mode="$1"
    info "Your ACI is Signal's own account identifier — a UUID, not a phone"
    info "number. Find it in Signal on your phone: Settings, tap your name,"
    info "then look for the account identifier."
    echo
    local owner_aci owner_number bot_number api_base key
    owner_aci="$(ask 'Your ACI (the owner, allowed to command it)')"
    owner_number="$(ask 'Your phone number, e.g. +15550000001')"
    bot_number="$(ask "The BOT's phone number (a separate number)")"
    api_base="$(ask 'API base URL' 'https://inference-api.nousresearch.com/v1')"
    key="$(ask 'API key (stored mode 600, never committed)')"

    [ -n "$owner_aci" ] || die "An ACI is required — it is the only authentication."

    printf '%s' "$key" > "$STATE/nous.key"
    chmod 600 "$STATE/nous.key"
    ok "wrote $STATE/nous.key (mode 600)"

    python3 - "$REPO/config.example.json" "$CONFIG" \
             "$owner_aci" "$owner_number" "$bot_number" "$api_base" \
             "$STATE" "$review_mode" <<'PY'
import json, sys
example, target, aci, owner, bot, api, state, review = sys.argv[1:9]
cfg = json.load(open(example))
cfg["owner_aci"] = aci
cfg["owner_number"] = owner
cfg["bot_number"] = bot
cfg["api_base"] = api
cfg["socket"] = state + "/socket"
cfg["key_file"] = state + "/nous.key"
cfg["monthly_review"] = review
json.dump(cfg, open(target, "w"), indent=2, ensure_ascii=False)
PY
    chmod 600 "$CONFIG"
    ok "wrote $CONFIG"
    info "Edit it to describe your services before relying on the health checks."
}

# ----------------------------------------------------------- review host ---

install_review_host() {
    # The review host has its own standalone script, so it can be set up with a
    # single curl and no clone. Defer to it rather than keeping two copies of
    # the same logic that can drift apart.
    local script="$REPO/install-review-host.sh"
    if [ -f "$script" ]; then
        exec bash "$script"
    fi
    exec bash -c "curl -fsSL https://raw.githubusercontent.com/chkiss/hongyan/main/install-review-host.sh | bash"
}

# ----------------------------------------------------------------- main ----

say "鸿雁 hongyan — installer"
info "One device:  everything on the server, including the monthly review."
info "Two devices: server here, richer monthly review on another machine"
info "             with more memory and a full agent."
echo

SETUP="$(ask 'Setup — one or two devices? (1/2)' '1')"

case "$SETUP" in
1|one|One|ONE)
    install_server "local"
    ;;
2|two|Two|TWO)
    echo
    info "Which machine is this?"
    info "  s) the server that runs the assistant"
    info "  r) the review host that audits it monthly"
    ROLE="$(ask 'Role (s/r)' 's')"
    case "$ROLE" in
        s|S|server) install_server "remote" ;;
        r|R|review) install_review_host ;;
        *) die "Unrecognised role: $ROLE" ;;
    esac
    ;;
*)
    die "Unrecognised setup: $SETUP"
    ;;
esac
