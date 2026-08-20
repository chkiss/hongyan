"""Tests for the Signal assistant.

No network, no Signal account, no model calls: everything here is either pure
logic or a stubbed loop. Run with `python3 tests/test_listener.py` from the
repo root, or under pytest.

Each test names the defect it exists to prevent. Most of them are regressions
that reached production first.
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The module reads its config at import time, so give it a throwaway home.
_TMP = tempfile.mkdtemp(prefix="siglistener-test-")
os.environ["HOME"] = _TMP
os.makedirs(os.path.join(_TMP, ".config", "hongyan"))
shutil.copy(os.path.join(ROOT, "config.example.json"),
            os.path.join(_TMP, ".config", "hongyan", "config.json"))
open(os.path.join(_TMP, ".config", "hongyan", "nous.key"), "w").write("test-key")

spec = importlib.util.spec_from_file_location(
    "sl", os.path.join(ROOT, "hongyan_listener.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

FAILURES = []


def check(name, got, want):
    if got == want:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s\n       got:  %r\n       want: %r" % (name, got, want))
        FAILURES.append(name)


def section(title):
    print("\n%s" % title)


# ---------------------------------------------------------------- logging ---
section("audit log integrity")

# A newline in message text used to split one record into several TSV rows,
# so `cut -f2 | uniq -c` reported event types that were really message text.
m.audit("test", "line one\nline two\twith tab")
rows = [l for l in open(m.AUDIT_FILE) if "line one" in l]
check("newline stays on one row", len(rows), 1)
check("tab is escaped", "\\t" in rows[0], True)

# Bare slices ended mid-word, making a clipped line and a split line
# indistinguishable from a real defect.
check("clip marks the cut", m.clip("x" * 300).endswith("…"), True)
check("clip respects the limit", len(m.clip("x" * 300)), m.AUDIT_DETAIL)
check("short text untouched", m.clip("short"), "short")


# ----------------------------------------------------------------- quotes ---
section("quote resolution")

now = time.time()
hist = [
    {"ts": now - 3600, "user": "why is 了 placed there?",
     "assistant": "Because it marks completion of the whole event.",
     "reply_ts": [1000000000001], "user_ts": 1000000000000, "sources": []},
    {"ts": now - 86400 * 3, "user": "what is a modal verb?",
     "assistant": "A verb expressing possibility or obligation.",
     "reply_ts": [900000000005], "user_ts": 900000000004, "sources": []},
]
json.dump(hist, open(m.HISTORY_FILE, "w"))

check("exact id, bot message",
      m.resolve_quote({"id": 900000000005, "text": "A verb expressing"})[1], "hit")
check("exact id, user's own message",
      m.resolve_quote({"id": 1000000000000, "text": "anything"})[1], "hit")
# Every turn written before timestamps existed has none, so text must work.
check("text fallback for pre-existing history",
      m.resolve_quote({"id": 999, "text": "Because it marks completion of the whole event."})[1],
      "hit")
check("aged out past retention",
      m.resolve_quote({"id": int((now - 86400 * 30) * 1000), "text": "old"})[1], "too_old")
# An unplaceable quote must be reported, never silently answered as if absent.
check("unresolved is reported",
      m.resolve_quote({"id": int((now - 60) * 1000), "text": "never said this"})[1],
      "unresolved")
check("no quote", m.resolve_quote(None)[1], "none")
check("resolves to the right turn",
      m.resolve_quote({"id": 900000000005, "text": "A verb"})[0]["user"],
      "what is a modal verb?")


# ------------------------------------------------------------------ queue ---
section("queue")

open(m.QUEUE_FILE, "w").close()
m.queue_note("remind me to call the vet")
m.queue_note("check the drafts")
m.queue_note("remember to renew certs")
check("reminder detected", m.load_queue()[0]["kind"], "reminder")
check("plain note detected", m.load_queue()[1]["kind"], "freetext")

items = m.load_queue()
for i in items:
    i["ts"] = time.time() - 86400 * 2
m.save_queue(items)

# The displayed number must be the number that works: numbering over the whole
# file showed "2." while `done 2` answered "no open item 2".
nums = [n for n, _ in m.pending_items()]
check("numbered from 1 over open items", nums, [1, 2, 3])
m.t2_done("2")
check("renumbered after clearing", [n for n, _ in m.pending_items()], [1, 2])
check("cleared item is gone",
      any("drafts" in i["text"] for _, i in m.pending_items()), False)
check("out-of-range rejected", m.t2_done("9").startswith("no open item"), True)
check("non-numeric rejected", m.t2_done("x").startswith("which one"), True)

# A digest must be silent unless something has actually been waiting.
check("digest lists stale items", "renew certs" in m.queue_digest(), True)
m.t2_done("all")
check("digest empty when queue empty", m.queue_digest(), "")
m.queue_note("remind me about something new")
check("digest silent for same-day items", m.queue_digest(), "")


# ------------------------------------------------------- step deduplication ---
section("near-duplicate steps")

# The pair the user actually noticed ("You searched twice").
check("catches the real near-duplicate",
      m._similar(m._norm('French expression "oh la France" meaning origin wh'),
                 m._norm('French expression "oh la France" meaning origin')), True)
check("allows a genuine refinement",
      m._similar(m._norm("grammar valid ask when return"),
                 m._norm("grammar correct ask when return chinese usage")), False)
check("unrelated topics differ",
      m._similar(m._norm("chinese modal verbs"), m._norm("tour de france history")), False)


# ------------------------------------------------------- loop termination ---
section("agent loop termination")

# A rejected step no longer spends budget, so every `continue` has to draw on
# the rejection allowance or the loop can spin forever.
m.web_search = lambda q: ("results", "example.com", ["http://ok.test/1"])
m.fetch_text = lambda u, n=2500: "prose " * 200
m.fetch_site = lambda h, n=2500: ("prose " * 200, h)
m.prose_score = lambda t: 999
m.run_probe = lambda n: "probe output"

LIMIT = 60


def loop_calls(decider):
    calls = {"n": 0}

    def decide(*a, **k):
        calls["n"] += 1
        if calls["n"] > LIMIT:
            raise RuntimeError("did not terminate")
        return decider(calls["n"])

    m.decide = decide
    ctx, _ = m.gather("a question", "", "", None, [])
    return calls["n"], len(ctx)


budget = m.CFG.get("max_steps", 5)
for label, decider in [
        ("identical search forever", lambda n: ("search", "same query")),
        ("near-duplicate forever", lambda n: ("search", "oh la France origin" + " wh"[:n % 3])),
        ("fresh invalid URL each time", lambda n: ("open", "http://evil%d.test/x" % n)),
]:
    try:
        calls, _ = loop_calls(decider)
        check("%s terminates within budget+2" % label, calls <= budget + 2, True)
    except RuntimeError as exc:
        check("%s terminates" % label, str(exc), "")

calls, blocks = loop_calls(lambda n: ("search", "distinct query %d" % n))
# The point of not charging for a rejection: real work still gets the full run.
check("distinct searches use the whole budget", blocks, budget)


# --------------------------------------------------- provider availability ---
section("a vanished model reports itself")

# There is no scheduled availability check: nothing may contact the provider on
# a timer. A model that has gone is detected from a call that actually failed,
# which is a request a person caused by sending a message.
sent = []
m.subprocess.run = lambda *a, **k: sent.append(a[0][-1]) or type("R", (), {"returncode": 0})()
os.path.exists(m.MODEL_GONE_FILE) and os.remove(m.MODEL_GONE_FILE)

m.note_model_gone("some/model:free", Exception("HTTP Error 404: Not Found"))
check("404 raises the alarm", len(sent), 1)
check("names the model", "some/model:free" in sent[0], True)

# A withdrawn model fails on every later call; repeating the warning each time
# would turn a useful message into noise.
m.note_model_gone("some/model:free", Exception("HTTP Error 404: Not Found"))
check("does not repeat within a day", len(sent), 1)

# An ordinary blip is not a disappearance.
m.note_model_gone("other/model:free", Exception("timed out"))
check("timeout stays quiet", len(sent), 1)
m.note_model_gone("other/model:free", Exception("requires available credits"))
check("credit wall raises the alarm", len(sent), 2)

# The monthly review must not reach the provider unless explicitly allowed.
check("roster polling is off by default", bool(m.CFG.get("roster_check")), False)
reached = []
m.fetch_roster = lambda: reached.append(1) or {}
m.monthly_review()
check("monthly review made no provider request", reached, [])


# -------------------------------------------------------------- transports ---
section("note-to-self transport")

OWNER = m.CFG["owner_aci"]
OTHER = "99999999-8888-7777-6666-555555555555"

# Default transport: an ordinary incoming message to the bot's own account.
m.TRANSPORT = "bot_account"
data, src = m.extract_message({"sourceUuid": OWNER, "dataMessage": {"message": "hello"}})
check("bot account reads dataMessage", (data or {}).get("message"), "hello")
check("bot account reports the sender", src, OWNER)

# Linked-device mode. A linked device receives a copy of EVERY conversation,
# so the filter is the whole security story: only a note to yourself may pass.
m.TRANSPORT = "note_to_self"
note = {"sourceUuid": OWNER,
        "syncMessage": {"sentMessage": {"message": "what is my disk usage?",
                                        "destinationUuid": OWNER}}}
data, src = m.extract_message(note)
check("note to self is accepted", (data or {}).get("message"), "what is my disk usage?")

# The dangerous case: something the owner sent to a friend. It reaches the
# linked device identically and must never be read.
to_friend = {"sourceUuid": OWNER,
             "syncMessage": {"sentMessage": {"message": "private message to a friend",
                                             "destinationUuid": OTHER}}}
check("message to someone else is dropped", m.extract_message(to_friend)[0], None)

# A message FROM someone else, synced to the linked device.
from_friend = {"sourceUuid": OTHER, "dataMessage": {"message": "hi"}}
check("incoming from a third party is dropped", m.extract_message(from_friend)[0], None)

# Someone else's note to self, were it ever to arrive.
theirs = {"sourceUuid": OTHER,
          "syncMessage": {"sentMessage": {"message": "x", "destinationUuid": OTHER}}}
check("another account's note to self is dropped", m.extract_message(theirs)[0], None)

# In this mode a plain dataMessage is not the channel and must not be read.
check("dataMessage ignored in note-to-self mode",
      m.extract_message({"sourceUuid": OWNER, "dataMessage": {"message": "x"}})[0], None)

m.TRANSPORT = "bot_account"


# ------------------------------------------------------------ config load ---
section("config-driven site description")

check("services parsed from config", ("system", "nginx") in m.PROBES.values() or
      any(k == "nginx" for k in m.PROBES), True)
check("custom commands registered", "backups" in m.T1, True)
check("custom command has synonyms", "backups" in m.SYNONYMS, True)
check("custom probes registered", "backups" in m.PROBE_REGISTRY, True)
check("custom probe carries its command",
      "backup.log" in m.PROBE_REGISTRY["backups"][1], True)
# A config typo must not quietly redefine a built-in.
check("built-ins cannot be shadowed", m.T1["status"].__name__, "cmd_status")


# ---------------------------------------------------------------------------
shutil.rmtree(_TMP, ignore_errors=True)
print("\n%s" % ("FAILED: " + ", ".join(FAILURES) if FAILURES else "all tests passed"))
sys.exit(1 if FAILURES else 0)
