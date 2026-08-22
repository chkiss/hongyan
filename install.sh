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

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || REPO=""
CLONE_URL="${HONGYAN_REPO:-https://github.com/chkiss/hongyan}"
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

ask_valid() {  # ask_valid <prompt> <regex> <hint> [default]
    # Validates FORMAT only. Whether the value is the right ACI or a working
    # key cannot be checked here, and a wrong ACI is the nastiest of the two:
    # the listener drops unauthorised messages in silence, so the symptom is a
    # bot that ignores you with no error anywhere. Catching a typo at the point
    # it is typed is worth the few lines.
    local prompt="$1" pattern="$2" hint="$3" default="${4:-}" reply tries=0
    while true; do
        reply="$(ask "$prompt" "$default")"
        if printf '%s' "$reply" | grep -Eq "$pattern"; then
            printf '%s' "$reply"
            return 0
        fi
        tries=$((tries + 1))
        warn "$hint" >&2
        if [ "$tries" -ge 3 ]; then
            # Do not trap someone whose value is legitimately unusual.
            if confirm "Use \"$reply\" anyway?" >&2; then
                printf '%s' "$reply"
                return 0
            fi
            tries=0
        fi
    done
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
    # Drop only LEADING blank lines (an empty crontab produces one). The old
    # `/^$/d` stripped every blank line from an existing crontab too.
    printf '%s\n# %s\n%s %s\n' "$current" "$comment" "$schedule" "$command" \
        | sed '/./,$!d' | crontab -
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
    for f in hongyan_listener.py hongyan-lib.sh hongyan-supervise hongyan-watchdog hongyan-autoupdate hongyan-send.py hongyan-me; do
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
    add_cron "23 8 * * *" "$BIN/hongyan-watchdog --daily" "Daily health check"
    # No cron for the monthly review: it is offered in conversation after a
    # message you sent, and runs only if you reply yes. A scheduled send would
    # be an automated message — Signal's terms forbid that, and so does the
    # design. Type 'review' any time, or 'do the monthly review'.
    echo
    if confirm "Pull updates from GitHub automatically (every 15 min)?"; then
        add_cron "*/15 * * * *" "$BIN/hongyan-autoupdate" \
            "Fast-forward to origin/main when tests pass"
        info "Silent on success; alerts over Signal only if an update fails."
        info "Disable any time: crontab -e, remove the hongyan-autoupdate line."
    else
        info "Skipping auto-update. Update by hand with: git -C <checkout> pull"
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
    local uuid_re='^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
    local e164_re='^\+[1-9][0-9]{7,14}$'

    owner_aci="$(ask_valid 'Your ACI (the owner, allowed to command it)' "$uuid_re" \
        'That is not a UUID. It looks like 3f2504e0-4f89-11d3-9a0c-0305e82c3301.')"
    # Signal reports the ACI lowercase and the listener compares it as an exact
    # string. Storing what the user typed (one capital letter) would mean a bot
    # that silently ignores its owner forever.
    owner_aci="$(printf '%s' "$owner_aci" | tr '[:upper:]' '[:lower:]')"
    owner_number="$(ask_valid 'Your phone number' "$e164_re" \
        'Needs the country code and no spaces, e.g. +15550000001.')"

    echo
    info "How should hongyan reach you?"
    info "  1) Its own Signal account, on a second phone number  (recommended)"
    info "  2) Note to Self, by linking it as a device on YOUR account"
    local transport_choice
    transport_choice="$(ask 'Choice (1/2)' '1')"

    local transport="bot_account"
    bot_number=""
    if [ "$transport_choice" = "2" ]; then
        # The warning goes here, not only in the README: this is the moment the
        # decision is actually made, and it is not reversible by editing a
        # config file afterwards — the account has already been linked.
        echo
        warn "READ THIS BEFORE CHOOSING NOTE TO SELF"
        info ""
        info "  hongyan would be linked as a device on your own Signal account,"
        info "  the same way Signal Desktop is. A linked device receives a copy"
        info "  of EVERY conversation you have — not just Note to Self — and can"
        info "  send messages as you, to anyone."
        info ""
        info "  If this server is compromised, your whole Signal identity goes"
        info "  with it: your private conversations, and the ability to message"
        info "  your contacts while appearing to be you."
        info ""
        info "  With a separate bot account, the worst case is a spare number"
        info "  that only ever talks to you."
        info ""
        if confirm "I understand, and want Note to Self anyway"; then
            transport="note_to_self"
            ok "Note to Self selected"
            info "After this finishes, run:  signal-cli link -n hongyan"
            info "then scan the QR code with Signal on your phone."
            info "Revoke it any time under Settings > Linked Devices."
        else
            info "Keeping the separate bot account. Good call."
        fi
    fi

    if [ "$transport" = "bot_account" ]; then
        while true; do
            bot_number="$(ask_valid "The BOT's phone number (a SEPARATE number)" "$e164_re" \
                'Needs the country code and no spaces, e.g. +15550000002.')"
            [ "$bot_number" != "$owner_number" ] && break
            warn "The bot needs its own number, different from yours." >&2
            warn "One number means it would be messaging its own account." >&2
        done
    fi
    api_base="$(ask 'API base URL' 'https://opencode.ai/zen/v1')"
    key=""
    while true; do
        key="$(ask 'API key (optional for free tiers — Enter to skip)')"
        [ -n "$key" ] && break
        if confirm "No API key — continue without one?"; then
            break
        fi
    done

    if [ -n "$key" ]; then
        printf '%s' "$key" > "$STATE/zen.key"
        chmod 600 "$STATE/zen.key"
        ok "wrote $STATE/zen.key (mode 600)"
    else
        ok "no key stored — the listener calls the endpoint keyless"
    fi

    python3 - "$REPO/config.example.json" "$CONFIG" \
             "$owner_aci" "$owner_number" "$bot_number" "$api_base" \
             "$STATE" "$review_mode" "$transport" <<'PY'
import json, sys
example, target, aci, owner, bot, api, state, review, transport = sys.argv[1:10]
cfg = json.load(open(example))
    cfg["owner_aci"] = aci
    cfg["owner_number"] = owner
    cfg["bot_number"] = bot
    cfg["api_base"] = api
    cfg["socket"] = state + "/socket"
    cfg["key_file"] = state + "/zen.key"
    cfg["monthly_review"] = review
    cfg["transport"] = transport
json.dump(cfg, open(target, "w"), indent=2, ensure_ascii=False)
PY
    chmod 600 "$CONFIG"
    ok "wrote $CONFIG"
    info "Edit it to describe your services before relying on the health checks."
    echo
    warn "Only the FORMAT of those answers was checked."
    info "Nothing here can tell whether the ACI is really yours or the key works."
    info "If the ACI is wrong the bot will simply ignore you — unauthorised"
    info "messages are dropped on purpose, so there is no error to see."
    info "Confirm it by texting the bot 'status'. If nothing comes back, check:"
    info "  tail -f $STATE/audit.log     # a 'rejected' line means the ACI is wrong"
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

# Piped from curl, there is no checkout to install from and stdin is the
# script itself. Fetch the code first, then take answers from the terminal.
SELF_FETCHED=0
if [ -z "$REPO" ] || [ ! -f "$REPO/hongyan_listener.py" ]; then
    SELF_FETCHED=1
    REPO="${HONGYAN_DIR:-$HOME/hongyan}"
    if [ -d "$REPO/.git" ]; then
        printf '  Updating existing checkout at %s\n' "$REPO"
        git -C "$REPO" pull --quiet || printf '  (could not update; using what is there)\n'
    else
        command -v git >/dev/null || die "git is required to install this way."
        printf '  Fetching hongyan into %s\n' "$REPO"
        git clone --quiet "$CLONE_URL" "$REPO" || die "Could not clone $CLONE_URL"
    fi
    [ -f "$REPO/hongyan_listener.py" ] || die "$REPO does not look like a hongyan checkout."
fi

# Only when piped from curl: stdin is the script, so answers must come from the
# terminal. Run as a local script, piped input is a legitimate way to drive it
# (the sandbox does exactly that), so leave stdin alone.
if [ "$SELF_FETCHED" = 1 ] && [ ! -t 0 ]; then
    [ -e /dev/tty ] && exec < /dev/tty
    [ -t 0 ] || die "No terminal for prompts. Clone the repository and run ./install.sh directly."
fi

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
