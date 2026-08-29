#!/bin/bash
# Shared helpers for the hongyan shell tools. Sourced, never executed.
# One definition lives here so the copies in hongyan-supervise,
# hongyan-watchdog and anything later cannot drift apart.

# XDG roots, matching hongyan_listener.py exactly. Config is what a person
# copies between machines; state is logs and message content; runtime is the
# socket and the pids, which SHOULD die at boot. Sourced by every shell tool
# so the four roots have one definition, not six.
HY_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/hongyan"
HY_STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/hongyan"
HY_DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/hongyan"
if [ -n "${XDG_RUNTIME_DIR:-}" ]; then
    HY_RUN_DIR="$XDG_RUNTIME_DIR/hongyan"
else
    HY_RUN_DIR="$HY_STATE_DIR/run"
fi
export HY_CONFIG_DIR HY_STATE_DIR HY_DATA_DIR HY_RUN_DIR

hongyan_dirs() {
    # The runtime dir is wiped at boot, so every entry point recreates it.
    mkdir -p "$HY_CONFIG_DIR" "$HY_STATE_DIR" "$HY_RUN_DIR" 2>/dev/null
}

hongyan_alive() {
    # Liveness by PID file, not `pgrep -f`: pgrep matched unrelated processes
    # whose command line merely mentioned the name.
    local pf="$1" want="$2" pid
    [ -f "$pf" ] || return 1
    pid="$(cat "$pf" 2>/dev/null)"
    [ -n "$pid" ] || return 1
    [ -d "/proc/$pid" ] || return 1
    tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q -- "$want"
}
