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

DIR = os.path.expanduser("~/.config/signal-listener")
SOCK = os.path.join(DIR, "socket")
SIGNAL_CLI = os.path.expanduser("~/.local/bin/signal-cli")

# Numbers come from the same config the listener reads. They were hardcoded
# here, which is the one thing that made this file unpublishable — and it meant
# two places to edit if a number ever changed.
try:
    with open(os.path.join(DIR, "config.json")) as _fh:
        _CFG = json.load(_fh)
    BOT = _CFG["bot_number"]
    OWNER = _CFG["owner_number"]
except (OSError, ValueError, KeyError) as _exc:
    print("hongyan-send: cannot read bot_number/owner_number from %s/config.json: %s"
          % (DIR, _exc), file=sys.stderr)
    sys.exit(1)


def via_socket(text):
    if not os.path.exists(SOCK):
        return False
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(30)
        s.connect(SOCK)
        req = {"jsonrpc": "2.0", "id": "send1", "method": "send",
               "params": {"recipient": [OWNER], "message": text}}
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
    try:
        r = subprocess.run([SIGNAL_CLI, "-a", BOT, "send", "-m", text, OWNER],
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
