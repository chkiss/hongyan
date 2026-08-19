# signal-assistant

A read-only assistant for your own Linux server, reachable over Signal.

You text it a question. It decides for itself whether to search the web, read a
page, check the server, look at an image you sent, or just answer — then
replies. It can inspect the machine it runs on. It cannot change it.

```
you:  what's using all the memory?
bot:  sqlservr 420MB, Api 262MB, Identity 208MB — the Bitwarden stack is
      about 1.1GB of the 2.2GB in use.
      — via server:containers

you:  did the backup run last night?
bot:  yes, 04:17, hsklyrics.db -> Sync/mandoremi, no errors.

you:  [photo] how much is this set worth?
bot:  It's a Lego Technic 42096 Porsche 911 RSR, retired 2021...
      — via lite.bricklink.com
```

Built for one user and one server. It is not multi-tenant and does not want to
be.

---

## Why it is shaped this way

The interesting problem is not "call a model from a chat app". It is that the
model is **untrusted** and the server is **real**, and the assistant is useful
in proportion to how much it is allowed to look at.

The resolution is a rule applied everywhere:

> **The model emits a NAME. The code decides what that name means.**

The agent loop lets the model choose its next step — `search`, `open`, `probe`,
`weather`, `answer` — but it never emits a command. A `probe` action carries a
name that must exist in a registry defined by the owner's config; anything else
is dropped. An `open` action accepts a bare hostname, or a URL that a search
actually returned in this same turn, never one the model composed. There is no
shell, no filesystem access, no write path, and no credential in reach.

That property does not depend on the model behaving. It survives a bad model, a
jailbreak in a fetched web page, and a prompt-injection attempt in an image
caption, because at no point is model output interpreted as an instruction to
the machine.

### The permission tiers

| Tier | What | Reachable how |
|---|---|---|
| T1 | Read-only checks — disk, services, certs, boot history, containers | Typed command, synonym, or an agent probe |
| T2 | Reversible actions — restart an allowlisted unit, re-run an allowlisted job, clear a queue item | **Typed exactly by the owner.** A model may never route here |
| T3 | Anything destructive or outward-facing | **Does not exist** |

Free text is answered or queued — never executed. A classification is acted on
only when it names an allowlisted command.

### Authentication

Sender ACI only, which Signal validates cryptographically. Phone numbers appear
in the config as display attributes and are never used to authorize anything.
Messages arrive sealed-sender, so the text output shows no ACI at all — the JSON
API is the only correct source.

---

## What it does

- **Agent loop.** Up to 5 read-only steps per question, chosen by the model.
  It searches, opens pages, probes the server, checks weather, then answers.
- **Vision.** Photos are described first, and the description feeds the normal
  pipeline — so "how much is this worth?" produces both a look and a search.
- **Quote-replies.** Reply to any earlier message to force that thread as
  context, overriding the router. Confirmed by replying as a native Signal
  quote, so a wrong match is visible rather than baffling.
- **Follow-up routing.** A separate call decides which earlier turns matter and
  rewrites the message as a standalone question before any lookup.
- **A queue.** Anything that is a task, not a question, is kept and surfaced in
  a daily digest until cleared.
- **Self-supervision.** A watchdog restarts what dies, escalates over Signal
  when restarts keep failing, and reports downtime once recovered.

## What it refuses to do

It will not run commands, install packages, restart system units, edit files,
or message anyone else. Asked to, it says so — and says so *deterministically*,
because a model asked politely not to claim otherwise will still sometimes
reply "done, I ran the upgrades." See the lessons below.

---

## Install

Requires `signal-cli` and a Signal account for the bot (a separate number —
sending to your own account with `--note-to-self` produces no notification,
which is the whole reason the bot account exists).

```sh
git clone https://github.com/YOURNAME/signal-assistant
cd signal-assistant
cp config.example.json ~/.config/signal-listener/config.json
$EDITOR ~/.config/signal-listener/config.json      # ACI, models, services
printf '%s' "$YOUR_API_KEY" > ~/.config/signal-listener/nous.key
chmod 600 ~/.config/signal-listener/nous.key
./signal-supervise                                  # starts daemon + listener
```

Then add to cron:

```cron
@reboot sleep 30 && /path/to/signal-supervise
*/10 * * * * /path/to/signal-watchdog --restart
23 8 * * *  /path/to/signal-watchdog --daily
```

Everything host-specific lives in the config — the machine's label, its home
directory, which services exist and how each is checked, extra commands, extra
probes. There is no second "scrubbed" copy of this code: the repository is what
runs.

```jsonc
"services": {
  "nginx":     {"type": "system"},
  "syncthing": {"type": "user", "unit": "syncthing"},
  "bitwarden": {"type": "port", "port": 8080}
}
```

`type` matters more than it looks: a user unit checked as a system unit always
reports inactive, so a healthy service looks dead.

## Tests

```sh
python3 tests/test_listener.py
```

No network, no Signal account, no model calls. Every test names the defect it
prevents; most are regressions that reached production first.

---

## Lessons

These are the ones that changed the design.

**A lookup miss must return an error, never an empty success.** Attachments are
stored by `id`, not by the sender's `filename` — which is `null` for an ordinary
phone photo. The join was wrong, the file was never found, and the image
describer returned "no description, no error". The caller read that as "no image
attached", so for a month the bot confidently replied *"No image appears to be
attached to your message"* to messages containing images. Nothing was logged,
so no review could find it. The bug was the silent failure, not the wrong join.

**State what the system CANNOT do, not just what it can.** Asked to "run the
updates", the guardrails held perfectly — nothing executed — but the model
replied "I'll run the upgrades now" and then, asked directly, *"Yes, they ran."*
Claiming a privileged action it structurally cannot perform is worse than
refusing: the owner would believe a server was patched. Now a deterministic
check injects a "NOTHING WAS RUN" fact into the context rather than trusting the
model to have read its instructions.

**Truncating output without saying so reads as a wrong answer, not a clipped
one.** Three independent caps — send, history store, history render — stacked
up so the second of two image descriptions vanished. The follow-up question was
then answered from a history that had also lost it. Long replies are now split
across numbered messages with an explicit marker when they are genuinely cut.

**Never cap tokens on a reasoning model.** It emits reasoning before content, so
any limit risks `finish_reason=length` with empty content. This broke three
separate times at three different limits before the cap was removed entirely.

**Prefer general mechanisms to hardcoded tables.** No per-site mirror map:
text-first hostnames are tried and scored by a prose heuristic. No fixed
factbase: the model picks probe names from a registry. Every table that got
replaced by a mechanism produced a better system.

**Measure before tuning.** The near-duplicate threshold for repeated agent steps
is 0.8 because 18 real same-action pairs put every genuine repeat at ≥0.80 and
the best false positive at 0.62. The step budget stayed at 5 because across 19
real turns only one ever reached it.

**An unexplained non-reply is indistinguishable from a crash.** Every drop path
— stale message, cooldown, kill switch, unresolvable quote — says something.

## License

MIT
