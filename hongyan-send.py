#!/usr/bin/env python3
"""
Send a Signal message to the owner.

Prefers the running daemon's JSON-RPC socket, because the daemon holds an
exclusive lock on the account — spawning a second signal-cli while it is up
would fail. Falls back to a direct signal-cli invocation when the daemon is
down, which is exactly the case the watchdog needs in order to alert.
"""

import json
import os
import socket
import subprocess
import sys

# Same XDG split as hongyan_listener.py: config where a person keeps config,
# the socket in the runtime dir where it dies at boot.
DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME")
                   or os.path.expanduser("~/.config"), "hongyan")
_RUN = (os.path.join(os.environ["XDG_RUNTIME_DIR"], "hongyan")
        if os.environ.get("XDG_RUNTIME_DIR")
        else os.path.join(os.environ.get("XDG_STATE_HOME")
                          or os.path.expanduser("~/.local/state"),
                          "hongyan", "run"))
SIGNAL_CLI = os.path.expanduser("~/.local/bin/signal-cli")

try:
    with open(os.path.join(DIR, "config.json")) as _fh:
        _CFG = json.load(_fh)
except (OSError, ValueError) as _exc:
    print("hongyan-send: cannot read %s/config.json: %s" % (DIR, _exc),
          file=sys.stderr)
    sys.exit(1)

OWNER = _CFG.get("owner_number")
if not OWNER:
    print("hongyan-send: owner_number missing from %s/config.json" % DIR,
          file=sys.stderr)
    sys.exit(1)

SOCK = os.path.expanduser(_CFG.get("socket") or os.path.join(_RUN, "socket"))
TRANSPORT = _CFG.get("transport", "bot_account")


def bot_number():
    """The bot's own number, or None when the config has none.

    Only the direct signal-cli fallback needs it. note_to_self installs have no
    bot account at all — demanding one here at import time killed every send,
    including the socket path that never uses it and the watchdog alerts that
    depend on them.
    """
    return _CFG.get("bot_number") or None


def via_socket(text):
    if not os.path.exists(SOCK):
        return False
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(30)
        s.connect(SOCK)
        params = {"recipient": [OWNER], "message": text}
        if TRANSPORT == "note_to_self":
            # Same as the listener's own sends: without this the message
            # arrives as a silent sync note and nobody sees it.
            params["notifySelf"] = True
        req = {"jsonrpc": "2.0", "id": "send1", "method": "send",
               "params": params}
        s.sendall((json.dumps(req) + "\n").encode())
        # Read until we see our response id, ignoring unrelated notifications.
        buf = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                return False
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if msg.get("id") == "send1":
                    return "error" not in msg
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def via_cli(text):
    bot = bot_number()
    if not bot:
        return False
    try:
        r = subprocess.run([SIGNAL_CLI, "-a", bot, "send", "-m", text, OWNER],
                           capture_output=True, text=True, timeout=120)
        return r.returncode == 0
    except Exception:
        return False


def main():
    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else sys.stdin.read()
    text = text.strip()
    if not text:
        print("hongyan-send: empty message", file=sys.stderr)
        return 1
    if via_socket(text):
        return 0
    if via_cli(text):
        return 0
    print("hongyan-send: both socket and direct send failed", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
