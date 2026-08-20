#!/bin/bash
# A sandbox for trying the installer, including the two-device flow, without
# touching anything real.
#
#   ./testbed.sh up      build the sandbox and drop you into it
#   ./testbed.sh server  run the installer as the SERVER machine
#   ./testbed.sh review  run the installer as the REVIEW HOST
#   ./testbed.sh show    print what the sandbox currently contains
#   ./testbed.sh down    delete it
#
# Three things are stubbed, because they are the only parts that reach outside:
#
#   crontab   file-backed fake, so your real crontab is never touched
#   ssh       runs the command locally against the sandbox's "server" HOME,
#             so the two-device flow works with no network and no keys
#   HOME      each role gets its own, so configs cannot collide
#
# Everything else — the installer, the config writer, the symlinking, the
# review brief, the tests — is the real thing.

set -uo pipefail

BED="${HONGYAN_TESTBED:-$HOME/hongyan-testbed}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SERVER_HOME="$BED/server-home"
REVIEW_HOME="$BED/review-home"
STUBS="$BED/stubs"
CRON_SERVER="$BED/cron-server.txt"
CRON_REVIEW="$BED/cron-review.txt"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

build() {
    rm -rf "$BED"
    mkdir -p "$SERVER_HOME" "$REVIEW_HOME" "$STUBS"
    : > "$CRON_SERVER"
    : > "$CRON_REVIEW"

    # A crontab that lives in a file.
    cat > "$STUBS/crontab" <<'SH'
#!/bin/bash
STORE="${CRONSTORE:?CRONSTORE unset}"
if [ "${1:-}" = "-l" ]; then cat "$STORE" 2>/dev/null; exit 0; fi
# Write via a temp file. `crontab -l | ... | crontab -` puts a reader and a
# writer on the same path, and truncating it first loses the input.
tmp="$(mktemp)"
cat > "$tmp"
mv "$tmp" "$STORE"
SH

    # An ssh that isn't. It maps any target to the sandbox's server HOME, so
    # the two-device flow really runs — same commands, same config edits — with
    # no network and no keys.
    #
    # It announces itself on every call. A silent stub made the installer print
    # "ok reached poo@pee.com with the key already configured", which is a lie
    # a sandbox must never tell: the whole point is to show what would happen,
    # and a fake success is indistinguishable from a real one.
    #
    # Targets containing "unreachable" fail, so the failure path is testable.
    cat > "$STUBS/ssh" <<SH
#!/bin/bash
args=()
for a in "\$@"; do
    case "\$a" in
        -o|-i|-p) shift_next=1 ;;
        *) if [ "\${shift_next:-0}" = 1 ]; then shift_next=0; else args+=("\$a"); fi ;;
    esac
done
target="\${args[0]:-}"
printf '\033[35m  [sandbox] ssh %s — simulated, running locally against the sandbox server\033[0m\n' "\$target" >&2
case "\$target" in
    *unreachable*)
        printf 'ssh: connect to host %s: Connection refused\n' "\$target" >&2
        exit 255 ;;
esac
unset 'args[0]'
cmd="\${args[*]}"
[ -z "\$cmd" ] && exit 0
HOME="$SERVER_HOME" CRONSTORE="$CRON_SERVER" PATH="$STUBS:\$PATH" bash -c "\$cmd"
SH

    # signal-cli is not installed here; the installer only warns about it.
    chmod +x "$STUBS"/*

    say "Sandbox built at $BED"
    printf '  server HOME  %s\n' "$SERVER_HOME"
    printf '  review HOME  %s\n' "$REVIEW_HOME"
    printf '  crontabs     %s\n               %s\n' "$CRON_SERVER" "$CRON_REVIEW"
    printf '\n  Now try:\n'
    printf '    %s server    # answer the prompts as the server\n' "$0"
    printf '    %s review    # then set up the review host against it\n' "$0"
    printf '    %s show      # inspect the result\n' "$0"
}

run_server() {
    [ -d "$BED" ] || { echo "No sandbox — run '$0 up' first."; exit 1; }
    say "Installer as the SERVER (sandboxed)"
    echo "  Suggested answers: setup 2, role s, then any ACI/numbers you like."
    echo "  A valid-looking ACI: 11111111-2222-3333-4444-555555555555"
    echo
    HOME="$SERVER_HOME" CRONSTORE="$CRON_SERVER" PATH="$STUBS:$PATH" \
        bash "$REPO/install.sh"
}

run_review() {
    [ -d "$BED" ] || { echo "No sandbox — run '$0 up' first."; exit 1; }
    [ -f "$SERVER_HOME/.config/hongyan/config.json" ] || {
        echo "Set the server up first: $0 server"; exit 1; }
    say "Review-host installer (sandboxed)"
    echo "  Enter any SSH target — it is simulated and says so."
    echo "  Use a target containing 'unreachable' to see the failure path."
    echo
    HOME="$REVIEW_HOME" CRONSTORE="$CRON_REVIEW" PATH="$STUBS:$PATH" \
        HONGYAN_BRIEF_URL="file://$REPO/docs/monthly-review-brief.md" \
        bash "$REPO/install-review-host.sh"
}

show() {
    [ -d "$BED" ] || { echo "No sandbox."; exit 1; }

    say "Server config"
    if [ -f "$SERVER_HOME/.config/hongyan/config.json" ]; then
        python3 - "$SERVER_HOME/.config/hongyan/config.json" <<'PY'
import json, sys
c = json.load(open(sys.argv[1]))
for k in ("owner_aci", "owner_number", "bot_number", "socket", "key_file",
          "monthly_review"):
    print("  %-16s %s" % (k, c.get(k)))
PY
    else
        echo "  (not installed yet)"
    fi

    say "Server commands"
    ls -1 "$SERVER_HOME/.local/bin" 2>/dev/null | sed 's/^/  /' || echo "  (none)"

    say "Server crontab"
    grep -v '^$' "$CRON_SERVER" 2>/dev/null | sed 's/^/  /' || echo "  (empty)"

    say "Review host"
    if [ -f "$REVIEW_HOME/.config/hongyan/monthly-review-brief.md" ]; then
        echo "  brief written"
    else
        echo "  (not set up yet)"
    fi

    say "Did the review host switch the server to remote?"
    python3 - "$SERVER_HOME/.config/hongyan/config.json" 2>/dev/null <<'PY' || echo "  (server not installed)"
import json, sys
c = json.load(open(sys.argv[1]))
mode = c.get("monthly_review")
print("  monthly_review = %s  %s" % (
    mode, "(correct for two-device)" if mode == "remote" else "(still local)"))
PY
}

case "${1:-up}" in
    up)     build ;;
    server) run_server ;;
    review) run_review ;;
    show)   show ;;
    down)   rm -rf "$BED"; echo "Sandbox removed.";  ;;
    *)      echo "Usage: $0 {up|server|review|show|down}"; exit 1 ;;
esac
