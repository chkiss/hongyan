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
import subprocess
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


# ------------------------------------------------------- json extraction ---
section("json object extraction")

# route() matched greedily and decide() non-greedily; each failed on a
# different shape of prose-wrapped model output.
check("plain object", m.parse_json_object('{"mode":"new"}'), {"mode": "new"})
check("prose around the object",
      m.parse_json_object('Sure! {"mode":"followup","turns":[1]} hope that helps'),
      {"mode": "followup", "turns": [1]})
# Non-greedy matching stopped at this inner brace and lost the rest.
check("brace inside a string value",
      m.parse_json_object('{"standalone":"use {x} here"}'),
      {"standalone": "use {x} here"})
check("array is not an object", m.parse_json_object('[1,2]'), None)
check("no json", m.parse_json_object('no json at all'), None)
check("empty input", m.parse_json_object(''), None)


# ------------------------------------------------------- loop termination ---
section("agent loop termination")

# A rejected step no longer spends budget, so every `continue` has to draw on
# the rejection allowance or the loop can spin forever.
m.web_search = lambda q: ("results", "example.com", ["http://ok.test/1"])
m.fetch_text = lambda u, n=2500: "prose " * 200
m.fetch_site = lambda h, n=2500: ("prose " * 200, h)
m.prose_score = lambda t: 999
_real_run_probe = m.run_probe
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

# Restore what this section stubbed — a leaked probe stub made every later
# self-knowledge test read "probe output".
m.run_probe = _real_run_probe


# --------------------------------------------------- provider availability ---
section("a vanished model reports itself")

# There is no scheduled availability check: nothing may contact the provider on
# a timer. A model that has gone is detected from a call that actually failed,
# which is a request a person caused by sending a message.
sent = []
_real_subprocess_run = m.subprocess.run
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

# Restore the real runner: this stub leaked into every later subprocess call,
# including the CLI-flag tests below.
m.subprocess.run = _real_subprocess_run

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


# ---------------------------------------------------------------- fetching ---
section("fetch refuses non-public hosts")

# Result URLs come off a search page, so they are semi-trusted input; a
# crafted one must not point the fetcher at this machine's own services.
# Numeric literals need no DNS, so these work offline.
check("loopback blocked", m._public_host("http://127.0.0.1:8080/x"), False)
check("rfc1918 blocked", m._public_host("http://10.1.2.3/"), False)
check("link-local metadata blocked",
      m._public_host("http://169.254.169.254/latest/meta-data/"), False)
check("ipv6 loopback blocked", m._public_host("http://[::1]/"), False)
check("public literal allowed", m._public_host("https://1.1.1.1/"), True)
check("unparseable url blocked", m._public_host("not a url"), False)


# ------------------------------------------------------------ attachments ---
section("mixed attachments")

_imgfile = os.path.join(_TMP, "testatt.jpg")
with open(_imgfile, "wb") as fh:
    fh.write(b"\xff\xd8" + b"0" * 32)

_orig_model_call = m.model_call
_orig_attach_dir = m.CFG.get("attachment_dir")
m.model_call = lambda *a, **k: "a red bicycle against a wall"
m.CFG["attachment_dir"] = _TMP

desc, err = m.describe_image("what is this", [
    {"id": "testatt", "contentType": "image/jpeg"},
    {"id": "report", "contentType": "application/pdf"},
])
check("image still described beside a pdf", err, None)
check("description present", desc.startswith("a red bicycle"), True)
check("pdf noted as skipped", "application/pdf" in desc, True)

desc2, err2 = m.describe_image("", [{"contentType": "video/mp4"}])
check("all-non-image still errors", (err2 is not None and "mp4" in err2), True)

m.model_call = _orig_model_call
if _orig_attach_dir is None:
    del m.CFG["attachment_dir"]
else:
    m.CFG["attachment_dir"] = _orig_attach_dir


# ------------------------------------------------------------------ offers ---
section("offers: pull-only periodic delivery")

# Nothing periodic may ever SEND itself; it waits here until an answer makes
# it go out. These checks hold the state machine together.
os.path.exists(m.OFFERS_FILE) and os.remove(m.OFFERS_FILE)
open(m.QUEUE_FILE, "w").close()

# A box that has never been reviewed is due at once — month one counts too.
check("a never-reviewed box is due", m.nudge_due(), "review")
check("review due when never run", m.review_due(m.load_offers()), True)
check("nudge prefers the review", m.nudge_due(), "review")

# Offering stamps the cycle — no second offer this month however much you chat.
offers = m.load_offers()
offers["review_offer"] = {"stamp": m._month_now(), "at": time.time(),
                          "outstanding": True}
m.save_offers(offers)
check("no re-offer after offering", m.nudge_due(), None)
check("offer still answerable inside its window",
      m.outstanding_nudge(m.load_offers()), "review")

# Bare phrases capture consent; sentences fall through to normal handling.
check("bare yes affirms", m.classify_reply("Yes"), "affirm")
check("go ahead affirms", m.classify_reply("  go ahead! "), "affirm")
check("half-sentence falls through", m.classify_reply("yes and also check nginx"), None)
check("decline recognised", m.classify_reply("Not now."), "decline")
check("plain chat is neither", m.classify_reply("what time is it in tokyo?"), None)


# ------------------------------------------------------- explicit requests ---
section("explicit review request runs without asking")

for text in ("do the monthly review", "run the review", "Do your monthly review!",
             "please run the monthly review", "review now", "send me the report"):
    check("runs on %r" % text, bool(m.REVIEW_RUN_RE.match(text)), True)
for text in ("does the monthly review still work?", "what did the review say?",
             "how was the review?", "i want a review of my portfolio",
             "did the review run", "do it"):
    check("ignores %r" % text, bool(m.REVIEW_RUN_RE.match(text)), False)


# --------------------------------------------------- offer window expiry -----
section("an ignored offer expires silently")

offers = m.load_offers()
offers["review_offer"]["at"] = time.time() - m.REVIEW_OFFER_TTL - 60
m.save_offers(offers)
offers = m.load_offers()
got = m.outstanding_nudge(offers)
m.save_offers(offers)
check("past the window it stops answering", got, None)
check("and stays quiet for the rest of the month",
      m.review_due(m.load_offers()), False)


# ------------------------------------------------------------ digest offer ---
section("digest rides along on its own day")

m.queue_note("an item left waiting long ago")
items = m.load_queue()
items[0]["ts"] = time.time() - 90000
m.save_queue(items)
os.path.exists(m.OFFERS_FILE) and os.remove(m.OFFERS_FILE)
offers = m.load_offers()
offers["last_review"] = m._month_now()  # take the review out of the picture
m.save_offers(offers)
check("digest due when items have waited", m.nudge_due(), "digest")
offers = m.load_offers()
offers["digest_offer"] = {"stamp": m._today_str(), "at": time.time(),
                          "outstanding": True}
m.save_offers(offers)
check("digest offered once per day", m.nudge_due(), None)
m.t2_done("all")


# ------------------------------------------------------------------- mute ----
section("mute finally means something")

os.path.exists(m.OFFERS_FILE) and os.remove(m.OFFERS_FILE)
with open(m.MUTE_FILE, "w") as fh:
    fh.write(str(time.time() + 3600))
check("muted silences every offer", m.nudge_due(), None)
os.remove(m.MUTE_FILE)
check("expired mute restores them", m.nudge_due(), "review")


# --------------------------------------------------------- review command ----
section("review command honours the mode")

_orig_mode = m.CFG.get("monthly_review")
m.CFG["monthly_review"] = "off"
check("off explains itself", "switched off" in m.cmd_review(), True)
m.CFG["monthly_review"] = "remote"
check("remote points elsewhere", "review host" in m.cmd_review(), True)
m.CFG["monthly_review"] = _orig_mode if _orig_mode is not None else "local"


# ------------------------------------------------------------------ chains ---
section("model chains")

# The shipped config prefers Ox Alpha Free everywhere it can serve, then Big
# Pickle, then the Hermes tier; vision needs image-capable models.
check("routing chain order", m.chain_for("routing"),
      ["x-preview-f-free", "big-pickle", "hy3-free"])
check("answering shares the text chain", m.chain_for("answering"),
      ["x-preview-f-free", "big-pickle", "hy3-free"])
check("vision chain is image-capable models", m.chain_for("vision"),
      ["x-preview-f-free", "mimo-v2.5-free"])

# A pre-chain config keeps working after an upgrade: answer model first,
# then the old router, then the old dedicated vision model.
_orig_cfg = dict(m.CFG)
for k in ("text_chain", "vision_chain"):
    m.CFG.pop(k, None)
m.CFG["model_answer"] = "a/answer"
m.CFG["model_classify"] = "b/classify"
m.CFG["model_vision"] = "c/vision"
legacy = m._build_chains()
check("legacy text chain, answer first",
      legacy["answering"], ["a/answer", "b/classify"])
check("legacy routing follows text", legacy["routing"], ["a/answer", "b/classify"])
check("legacy vision chain", legacy["vision"], ["c/vision"])
m.CFG.clear()
m.CFG.update(_orig_cfg)

roles = set(m.configured_models()["x-preview-f-free"].split("+"))
check("one id serving several roles is reported so", roles,
      {"routing", "answering", "vision"})


# ----------------------------------------------------------- classification ---
section("failure triage")

check("timeout is temporary",
      m.classify_failure("<urlopen error timed out>"), "temporary")
check("overload is temporary",
      m.classify_failure("HTTP Error 503: Service Unavailable"), "temporary")
check("rate limit is temporary",
      m.classify_failure("HTTP Error 429: Too Many Requests"), "temporary")
check("cap wall wants a human",
      m.classify_failure('402 {"error":{"message":"Free usage exceeded, add credits"}}'),
      "review")
check("withdrawn model wants a human",
      m.classify_failure("HTTP Error 404: Not Found — no such model"), "review")
check("bad key wants a human",
      m.classify_failure("HTTP Error 401: Unauthorized invalid api key"), "review")
# Disabling a channel on evidence we do not understand would be worse than
# retrying, so unknown errors stay temporary.
check("unknown error stays temporary", m.classify_failure("something odd"), "temporary")


# ------------------------------------------------------------ bench windows ---
section("bench windows")

os.path.exists(m.MODEL_STATE_FILE) and os.remove(m.MODEL_STATE_FILE)

m.bench_model("temp/model", "overloaded", seconds=m.TEMP_COOLDOWN_SECONDS)
rec = m._load_model_state()["temp/model"]
check("temporary bench has a deadline",
      rec["until"] is not None and rec["until"] > time.time(), True)
check("temporary bench is short", rec["until"] - time.time() <= m.TEMP_COOLDOWN_SECONDS + 5, True)
state = m._load_model_state()
state["temp/model"]["until"] = time.time() - 1
m.save_offers  # noqa: touch nothing; write state directly below
with open(m.MODEL_STATE_FILE, "w") as fh:
    json.dump(state, fh)
check("expired cooldown frees the channel", m._usable("temp/model"), True)

m.bench_model("gone/model", "404 no such model", seconds=None)
check("indefinite bench blocks the channel", m._usable("gone/model"), False)


# ------------------------------------------------- answer-first failover ------
section("fallback answers before triage acts")

os.path.exists(m.MODEL_STATE_FILE) and os.remove(m.MODEL_STATE_FILE)
_real_once = m._request_once
events = []


def overload_then_ok(model, messages, max_tokens=None):
    events.append(model)
    if model == "x-preview-f-free":
        return None, "gateway overloaded"
    return "fallback says hi", None


m._request_once = overload_then_ok
out = m.model_call("routing", [{"role": "user", "content": "hi"}])
m._request_once = _real_once
check("the user got their answer", out, "fallback says hi")
check("chain walked in order", events,
      ["x-preview-f-free", "big-pickle"])
rec = m._load_model_state().get("x-preview-f-free") or {}
check("overload earned only a cooldown",
      rec.get("until") is not None and rec.get("until", 0) > time.time(), True)
check("no action item for a transient blip",
      all(i.get("kind") != "action" for i in m.load_queue()), True)


# ------------------------------------------------ dead channel, human needed --
section("a dead channel benches until the user looks")

_real_subproc = m.subprocess.run
open(m.QUEUE_FILE, "w").close()
os.path.exists(m.MODEL_STATE_FILE) and os.remove(m.MODEL_STATE_FILE)
os.path.exists(m.MODEL_GONE_FILE) and os.remove(m.MODEL_GONE_FILE)
alerts = []
m.subprocess.run = lambda *a, **k: alerts.append(a[0][-1]) or type(
    "R", (), {"returncode": 0})()


def capped_then_ok(model, messages, max_tokens=None):
    if model == "x-preview-f-free":
        return None, ('402 {"error":{"message":"Free usage exceeded, '
                      'add credits https://opencode.ai/zen"}}')
    return "saved by big-pickle", None


m._request_once = capped_then_ok
out = m.model_call("routing", [{"role": "user", "content": "hi"}])
m._request_once = _real_once
check("fallback still answered", out, "saved by big-pickle")
check("channel benched indefinitely",
      m._load_model_state().get("x-preview-f-free", {}).get("until"), None)
check("alert went out immediately", len(alerts), 1)
check("alert names the remedy", "use x-preview-f-free" in alerts[0], True)
actions = [i for _, i in m.pending_items() if i.get("kind") == "action"]
check("exactly one action item queued", len(actions), 1)

# A benched channel is skipped on later calls, so the duplicate-item guard is
# exercised by raising again directly.
m.raise_action_item("x-preview-f-free", "still failing later")
actions = [i for _, i in m.pending_items() if i.get("kind") == "action"]
check("repeat failure adds no second chore", len(actions), 1)

digest = m.queue_digest()
check("fresh action item surfaces in the digest at once",
      ("needs a decision" in digest and "x-preview-f-free" in digest), True)


# ------------------------------------------------------------------ restore ---
section("'use' puts a channel back")

m._request_once = lambda mdl, msgs, max_tokens=None: (
    ("OK", None) if mdl == "x-preview-f-free" else (None, "nope"))
reply = m.t2_use("x-preview-f-free")
check("restored after probe succeeded",
      reply.startswith("restored x-preview-f-free — back in service"), True)
check("bench cleared", m._usable("x-preview-f-free"), True)
check("matching action item closed",
      all(i.get("kind") != "action" for i in m.load_queue() if not i.get("done")), True)
check("unknown model refused", m.t2_use("not-a-model").startswith("refused"), True)
m._request_once = _real_once
m.subprocess.run = _real_subproc


# ------------------------------------------------------------------ soul -----
section("soul.md stays true")

# The doc is the model's self-knowledge; a stale line here becomes a confident
# wrong answer there. Structure, not prose, is what the tests pin.
text = m.soul_text()
check("exists", bool(text), True)
check("short enough to inject every answer", len(text) <= 4000, True)

import re as _re
import urllib.parse as _up

urls = _re.findall(r"https?://\S+", text)
check("has links at all", len(urls) >= 2, True)
check("every link is https", all(u.startswith("https://") for u in urls), True)
check("every link parses",
      all(_up.urlparse(u).netloc and "." in _up.urlparse(u).netloc for u in urls), True)

backticked = set(_re.findall(r"`([a-z]+)`", text))
stray = backticked - set(m.T1) - set(m.T2) - {"all"}
check("every command it mentions is real", stray, set())

block = m.soul_block()
check("injected block wraps the doc", text[:40] in block, True)

_real_soul_path = m.SOUL_PATH
m.SOUL_PATH = "/nonexistent/soul.md"
check("missing doc degrades quietly", (m.soul_text(), m.soul_block()), ("", ""))
m.SOUL_PATH = _real_soul_path


# ------------------------------------------------------------ soul gate ------
section("soul is injected only for meta-questions")

# Two free signals, unioned: a local regex and the router's verdict riding
# along in its existing JSON. Neither may cost an extra model call.
for text in ("who are you?", "who made you?", "what's your name",
             "where does your source code live?", "are you open source?",
             "how do you work?", "hongyan ne demek?", "what can't you do?",
             "who built this thing?"):
    check("meta: %r" % text, m._looks_meta(text), True)
for text in ("what's the weather in tokyo", "check disk space",
             "is nginx running?", "who won the match last night",
             "remind me to call the vet"):
    check("ordinary: %r" % text, m._looks_meta(text), False)

# The router's vote rides in its JSON; parse it out.
_captured = {}
_real_mc = m.model_call
_real_route = m.route
_real_gather = m.gather


def fake_route_model(model, messages, max_tokens=None):
    _captured["prompt"] = messages[0]["content"]
    return '{"mode":"new","turns":[],"standalone":"x","meta":true}'


m.model_call = fake_route_model
turns, standalone, meta = m.route("anything")
check("router verdict surfaces as third return", meta, True)
check("routing contract mentions the meta field",
      '"meta":false' in _captured.get("prompt", ""), True)


def route_no_meta(t):
    return [], t, False


def route_meta(t):
    return [], t, True


# ------------------------------------------------- end-to-end injection ------
section("soul injection end-to-end")

captured_systems = []


def capture_answer_model(role, messages, max_tokens=None):
    captured_systems.append(messages[0]["content"])
    return "a short reply"


def gather_stub(*a, **k):
    return [], False


m.model_call = capture_answer_model
m.gather = gather_stub

m.route = route_no_meta
m.answer("who are you?")
check("regex alone injects", any("WHO YOU ARE" in s for s in captured_systems), True)

captured_systems.clear()
m.answer("what's the weather in tokyo")
check("ordinary question stays lean",
      all("WHO YOU ARE" not in s for s in captured_systems), True)

captured_systems.clear()
m.route = route_meta
m.answer("some oddly phrased self question the regex never saw coming")
check("router vote alone injects",
      any("WHO YOU ARE" in s for s in captured_systems), True)

captured_systems.clear()
_real_meta_re = m._META_RE
m._META_RE = _re.compile(r"never-matches-anything")
m.route = route_no_meta
m.answer("who are you?")
check("both signals silent means no doc",
      all("WHO YOU ARE" not in s for s in captured_systems), True)

# restore everything the section touched
m._META_RE = _real_meta_re
m.model_call = _real_mc
m.route = _real_route
m.gather = _real_gather


# ------------------------------------------------- review mode gating --------
section("review offers honour the mode")

# A machine whose review is owned elsewhere (monthly_review=remote) must
# never be offered one — the yes that followed used to vanish into an
# unaudited parenthetical.
os.path.exists(m.OFFERS_FILE) and os.remove(m.OFFERS_FILE)
open(m.QUEUE_FILE, "w").close()
_orig_review_mode = m.CFG.get("monthly_review")

for mode, want in (("remote", None), ("off", None), ("local", "review")):
    m.CFG["monthly_review"] = mode
    check("nudge under monthly_review=%s" % mode, m.nudge_due(), want)

m.CFG["monthly_review"] = "remote"
reply = m.deliver_nudge("review")
check("remote explains itself plainly",
      ("review host" in reply and "quiet" in reply), True)
rows = [l for l in open(m.AUDIT_FILE) if "review_unavailable" in l]
check("the silent state change is audited now", len(rows) >= 1, True)
check("offer consumed without pretending it ran",
      (m.load_offers()["last_review"], m.load_offers()["review_offer"]["outstanding"]),
      ("", False))

m.CFG["monthly_review"] = "off"
check("off explains itself too", "switched off" in m.deliver_nudge("review"), True)

m.CFG["monthly_review"] = _orig_review_mode if _orig_review_mode else "local"


# ------------------------------------------------------ self-knowledge -------
section("the assistant can answer questions about itself")

code = m.run_probe("code")
check("code probe names running code", code.startswith("running code:"), True)
check("code probe shows branch sync", "branch:" in code, True)

state = m.run_probe("assistant_state")
check("covers review arrangement", "monthly review:" in state, True)
check("covers benched channels", "model channels benched:" in state, True)
check("covers queue", "queue:" in state, True)


# ------------------------------------------------- autoupdate lock -----------
section("the updater never leaves its lock to a survivor")

# A flock outlives its holder while any process keeps the fd open: the
# updater's first restart handed the lock to the new listener, and every
# update after that exited silently at flock -n. Pin the close-on-exec.
src = open(os.path.join(ROOT, "hongyan-autoupdate")).read()
check("lock is taken on a dedicated fd", "exec 9>" in src, True)
check("supervise runs with the lock fd closed",
      _re.search(r'supervise"\s+9>&-', src) is not None, True)


# ------------------------------------------------------------- cli flags ---
section("unknown cli flag dies")

listener_py = os.path.join(ROOT, "hongyan_listener.py")
r = subprocess.run([sys.executable, listener_py, "--digets"],
                   capture_output=True, text=True)
# A typo used to fall through to main() and start connecting as a daemon.
check("typo exits 2, does not connect", r.returncode, 2)
check("names the valid flags", "--digest" in r.stderr, True)

r2 = subprocess.run([sys.executable, listener_py, "--digest"],
                    capture_output=True, text=True)
check("known flag exits cleanly", r2.returncode, 0)


# ---------------------------------------------------------------------------
shutil.rmtree(_TMP, ignore_errors=True)
print("\n%s" % ("FAILED: " + ", ".join(FAILURES) if FAILURES else "all tests passed"))
sys.exit(1 if FAILURES else 0)
