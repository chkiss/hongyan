#!/bin/bash
# Shared helpers for the hongyan shell tools. Sourced, never executed.
# One definition lives here so the copies in hongyan-supervise,
# hongyan-watchdog and anything later cannot drift apart.

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
