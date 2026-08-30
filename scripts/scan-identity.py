#!/usr/bin/env python3
"""Refuse to let identity leave this machine in the repo.

The separation is already there — every real value lives in
``~/.config/hongyan/config.json``, which is gitignored and never tracked —
but it was being enforced by whoever remembered to read the diff. It got
caught once by hand: the owner's real ACI shipped in install.sh as the
"example" UUID and had to be scrubbed out of history. Remembering is not a
control; this is.

Two independent checks, because each catches what the other misses:

1. BY VALUE. The live config is read (never printed, never copied) and each
   identity value is hashed. Anything in the repo hashing to the same thing
   is the real value, whatever it is calling itself. This is exact and has no
   opinion about format — but it only works on the machine that holds the
   config.

2. BY SHAPE. Phone numbers, UUIDs, API keys and JWTs are matched by pattern,
   with the project's documented placeholders allowed. This works on any
   clone, including a fresh one on a machine with no config at all, and it is
   what catches a teammate's identity rather than the owner's.

Exit 0 clean, 1 with findings printed. --staged scans what is about to be
committed; --range A..B scans every blob the commits in that range introduce,
which is what a push actually hands to GitHub; the default scans everything
tracked.

--range exists because the commit hook only sees commits made through it. A
push can carry commits made in another clone, with --no-verify, or rebased
back into the branch, and a secret that was added and then deleted two commits
later is still in the history being pushed. Scanning the range's blobs — not
just the tip tree — is the difference between checking what the branch looks
like now and checking what is actually leaving the machine.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

CONFIG = os.path.expanduser("~/.config/hongyan/config.json")
# Repo-rooted on purpose: run from any directory, scan the same thing. A
# scanner that quietly finds no files when the cwd is wrong is worse than no
# scanner, because it reports success.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Values the project ships on purpose. Anything shaped like identity that is
# NOT one of these is a finding.
PLACEHOLDERS = {
    "+15550000000", "+15550000001", "+15550000002",
    "00000000-0000-0000-0000-000000000000",
    "11111111-2222-3333-4444-555555555555",
    "99999999-8888-7777-6666-555555555555",
    "3f2504e0-4f89-11d3-9a0c-0305e82c3301",  # the RFC's own example UUID
}

PATTERNS = [
    ("phone", re.compile(r"\+\d{10,15}\b")),
    ("uuid", re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                        r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")),
    ("api key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")),
    ("bearer token", re.compile(r"\beyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{8,}")),
]

# Identity fields in config.json. Nested values are walked too, so a future
# field does not quietly fall outside the check.
IDENTITY_KEYS = ("owner_aci", "owner_number", "bot_number", "aci", "number",
                 "phone", "uuid", "key", "token", "secret")


def _secret_hashes():
    """sha256 of every identity-ish value in the live config. Values stay put."""
    try:
        with open(CONFIG) as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return {}
    out = {}

    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, "%s.%s" % (path, k) if path else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, "%s[%d]" % (path, i))
        elif isinstance(node, str) and len(node) >= 8:
            leaf = path.rsplit(".", 1)[-1]
            if any(k in leaf.lower() for k in IDENTITY_KEYS):
                out[hashlib.sha256(node.encode()).hexdigest()] = path
    walk(cfg)
    return out


def _git(*args):
    return subprocess.run(("git", "-C", REPO) + args, capture_output=True)


def _tracked_files(staged):
    args = (("diff", "--cached", "--name-only", "--diff-filter=ACM")
            if staged else ("ls-files",))
    out = _git(*args).stdout.decode("utf-8", "replace")
    return [n for n in out.split("\n") if n.strip()]


def _content(path, staged):
    if staged:
        r = _git("show", ":" + path)
        return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""
    try:
        with open(os.path.join(REPO, path), encoding="utf-8",
                  errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _range_blobs(rev_range):
    """(label, blob sha) for every file version the range introduces.

    Deduplicated by blob sha: a file untouched across twenty commits is one
    blob and gets scanned once, so the cost tracks what actually changed
    rather than the length of the range.
    """
    out, seen = [], set()
    revs = _git("rev-list", rev_range).stdout.decode().split()
    for commit in revs:
        raw = _git("diff-tree", "-r", "--no-commit-id", "--diff-filter=ACM",
                   commit).stdout.decode("utf-8", "replace")
        for line in raw.split("\n"):
            if not line.startswith(":"):
                continue
            meta, _, path = line.partition("\t")
            fields = meta.split()
            if len(fields) < 4:
                continue
            blob = fields[3]
            if blob in seen or set(blob) == {"0"}:
                continue
            seen.add(blob)
            out.append(("%s:%s" % (commit[:8], path), blob))
    return out


def _scan_text(path, text, secrets):
    findings = []
    for lineno, line in enumerate(text.split("\n"), 1):
        for label, pattern in PATTERNS:
            for hit in pattern.findall(line):
                if hit in PLACEHOLDERS:
                    continue
                digest = hashlib.sha256(hit.encode()).hexdigest()
                if digest in secrets:
                    findings.append("%s:%d: the real %s from config.json"
                                    % (path, lineno, secrets[digest]))
                else:
                    findings.append(
                        "%s:%d: %s that is not a known placeholder (%s…)"
                        % (path, lineno, label, hit[:6]))
    return findings


def scan(staged=False, rev_range=None):
    secrets = _secret_hashes()
    findings = []
    me = os.path.basename(__file__)

    if rev_range:
        for label, blob in _range_blobs(rev_range):
            if os.path.basename(label.split(":", 1)[1]) == me:
                continue  # this file names the placeholders it allows
            text = _git("cat-file", "blob", blob).stdout.decode(
                "utf-8", "replace")
            if text:
                findings += _scan_text(label, text, secrets)
        return findings

    for path in _tracked_files(staged):
        if os.path.basename(path) == me:
            continue
        text = _content(path, staged)
        if text:
            findings += _scan_text(path, text, secrets)
    return findings


if __name__ == "__main__":
    rev_range = None
    if "--range" in sys.argv:
        i = sys.argv.index("--range")
        if i + 1 >= len(sys.argv):
            print("scan-identity: --range needs a revision range", file=sys.stderr)
            sys.exit(2)
        rev_range = sys.argv[i + 1]

    found = scan(staged="--staged" in sys.argv, rev_range=rev_range)
    if not found:
        sys.exit(0)
    verb = "pushed" if rev_range else "committed"
    print("identity check FAILED — this must not be %s:\n" % verb, file=sys.stderr)
    for line in found:
        print("  " + line, file=sys.stderr)
    print("\nReal values belong in ~/.config/hongyan/config.json, which is "
          "gitignored.\nIf one of these is a deliberate example, add it to "
          "PLACEHOLDERS in scripts/scan-identity.py.", file=sys.stderr)
    sys.exit(1)
