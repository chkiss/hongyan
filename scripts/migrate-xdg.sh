#!/bin/bash
# One-shot: split ~/.config/hongyan into config / state / runtime / data.
#
# Everything used to live in the config directory — the config, the key, every
# log, the message history, the socket and the pids. This moves each file to
# the root that matches what it IS. Idempotent: run it twice and the second
# run finds nothing to do.
#
# The daemon must stop, not just the listener: it owns the socket, and the
# socket is one of the things moving. Both come back at the end.
set -uo pipefail

OLD="$HOME/.config/hongyan"
_hy_dir="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
for _lib in "$_hy_dir/../hongyan-lib.sh" "$HOME/.local/bin/hongyan-lib.sh"; do
    [ -f "$_lib" ] && { . "$_lib"; break; }
done
: "${HY_STATE_DIR:?hongyan-lib.sh not found — cannot resolve the new layout}"

# STATE: logs, message content, everything that accumulates.
STATE_FILES=(audit.log audit.log.1 cli.log daemon.log listener.log watchdog.log
             update.log history.json queue.jsonl queue.jsonl.bak seen.json
             offers.json usage.json roster.json model_state.json
             model_gone.json nxdomain.json onboarding.json pending_images.json
             heartbeat memory.md muted-until disabled restart_fails down_since
             monthly-review-brief.md)
# RUNTIME: recreated on demand, correct to lose at boot.
RUN_FILES=(socket daemon.pid listener.pid update.lock recycle.lock)
# DATA: the speech-to-text weights.
DATA_FILES=(ggml-tiny.en.bin)

say() { printf '  %s\n' "$*"; }

[ -d "$OLD" ] || { echo "nothing at $OLD — nothing to migrate"; exit 0; }

echo "hongyan: migrating to the XDG layout"
say "config  $HY_CONFIG_DIR   (unchanged)"
say "state   $HY_STATE_DIR"
say "runtime $HY_RUN_DIR"
say "data    $HY_DATA_DIR"
echo

# ---- stop everything that holds a file open -------------------------------
for pf in "$OLD/listener.pid" "$HY_RUN_DIR/listener.pid"; do
    [ -f "$pf" ] && kill "$(cat "$pf")" 2>/dev/null
done
for _ in $(seq 1 25); do
    pgrep -u "$(id -u)" -f hongyan_listener >/dev/null || break
    sleep 1
done
pkill -u "$(id -u)" -9 -f hongyan_listener 2>/dev/null
for pf in "$OLD/daemon.pid" "$HY_RUN_DIR/daemon.pid"; do
    [ -f "$pf" ] && kill "$(cat "$pf")" 2>/dev/null
done
sleep 3
say "listener and daemon stopped"

mkdir -p "$HY_CONFIG_DIR" "$HY_STATE_DIR" "$HY_RUN_DIR" "$HY_DATA_DIR"
chmod 700 "$HY_STATE_DIR"   # it holds message content

moved=0
move_group() {
    local dest="$1"; shift
    local f
    for f in "$@"; do
        # A glob group (audit.log.1) may legitimately not exist.
        [ -e "$OLD/$f" ] || continue
        [ "$OLD/$f" -ef "$dest/$f" ] && continue
        if [ -e "$dest/$f" ]; then
            say "SKIP $f — already present in $dest"
            continue
        fi
        mv "$OLD/$f" "$dest/$f" && moved=$((moved + 1))
    done
}

move_group "$HY_STATE_DIR" "${STATE_FILES[@]}"
move_group "$HY_DATA_DIR" "${DATA_FILES[@]}"
# The socket and the pids are not moved — they are stale the moment the
# daemon stops. They are deleted, and supervise recreates them in the runtime
# dir on the way back up.
for f in "${RUN_FILES[@]}"; do
    rm -f "$OLD/$f"
done
# Inbound drops from the Hermes monthly-reply bridge, which writes dated files.
for f in "$OLD"/monthly-reply-*.txt; do
    [ -e "$f" ] || continue
    mv "$f" "$HY_STATE_DIR/" && moved=$((moved + 1))
done
say "moved $moved file(s)"

# ---- config.json: drop the pinned socket path -----------------------------
python3 - "$HY_CONFIG_DIR/config.json" <<'PY'
import json, sys, time
path = sys.argv[1]
try:
    with open(path) as fh:
        cfg = json.load(fh)
except (OSError, ValueError) as exc:
    print("  could not read config.json (%s) — leaving it alone" % exc)
    sys.exit(0)
if "socket" not in cfg:
    print("  config.json already has no pinned socket")
    sys.exit(0)
with open(path + time.strftime(".bak-%Y-%m-%d-%H%M%S"), "w") as fh:
    json.dump(cfg, fh, indent=2)
# The socket is a runtime path now. A config that pins /run/user/1000 is a
# config that breaks on the next machine, so the key comes out and the code
# derives it; anyone who needs an explicit one can put it back.
cfg.pop("socket")
tmp = path + ".tmp"
with open(tmp, "w") as fh:
    json.dump(cfg, fh, indent=2)
import os
os.replace(tmp, path)
print("  config.json: removed the pinned socket path")
PY

# ---- leave a sign for anyone looking in the old place ---------------------
if [ -d "$OLD" ]; then
    cat > "$OLD/MOVED.md" <<EOF
State and runtime files moved out of this directory on $(date '+%F').

  logs, queue, history, model state  ->  $HY_STATE_DIR
  socket, pids, locks                ->  $HY_RUN_DIR
  speech-to-text model               ->  $HY_DATA_DIR

config.json and the API key stay here — that is what this directory is for,
and it is now safe to copy or back up without carrying message content along.
EOF
fi

"$HOME/.local/bin/hongyan-supervise" >/dev/null 2>&1
sleep 8
if [ -S "$HY_RUN_DIR/socket" ]; then
    say "back up: socket at $HY_RUN_DIR/socket"
else
    say "WARNING: no socket at $HY_RUN_DIR/socket — check $HY_STATE_DIR/daemon.log"
fi
echo
echo "still in the config dir:"
ls -1 "$OLD" | sed 's/^/  /'
