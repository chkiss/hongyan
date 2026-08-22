# 鸿雁 · hongyan

A read-only assistant for your own Linux server, reachable over Signal, running entirely on free-tier language models.

*鸿雁 (hóngyàn), "wild goose" — the bird that carries letters in classical Chinese, from the story of an envoy who sent word home tied to a goose's leg. It flies a long way and delivers what it was given without having to be trusted like a courier.*

You text it a question. It works out for itself whether to search the web, read a page, check the server, look at a photo you sent, or just answer — then replies. It can inspect the machine it runs on. It can never change it.

```
you:  what's using all the memory?
bot:  mandoremi 512MB, syncthing 180MB, nginx 40MB — 2.2GB of 3.7GB in use,
      1.5GB available.
      — via server:memory, server:top_mem

you:  did the backup run last night?
bot:  yes, 04:17, hsklyrics.db -> Sync/mandoremi, no errors.

you:  [photo] how much is this set worth?
bot:  It's a Lego Technic 42096 Porsche 911 RSR, retired 2021, currently
      selling used around £90-120 depending on completeness.
      — via lite.bricklink.com
```

## It costs nothing to run

Everything runs through [OpenCode Zen](https://opencode.ai/zen) — an OpenAI-compatible gateway whose docs open it to *any* agent — on an ordered chain of free models. The first channel that answers wins; the rest are fallbacks:

| Tier | Model | Context | Vision | Notes |
|---|---|---|---|---|
| Preferred | `x-preview-f-free` — Ox Alpha Free | 1M | yes | Strongest here, and its provider keeps nothing (zero-retention) |
| Second | `big-pickle` | 200K | no | Stealth preview; its free period may train on traffic |
| Fallback | `hy3-free` (Hermes tier) | 190K | no | Weakest of the three; same free-period caveat |
| Vision fallback | `mimo-v2.5-free` | 200K | yes | Only reached if the preferred vision model is out |

Routing and answering share the text chain — with everything free there is no cost reason to route on a weaker model. The keyless free tier works today; a Zen API key (`key_file`) makes your usage attributable to an account instead of an IP address.

Bring your own account and terms. hongyan is a client, not a service: it never proxies anyone else's access. Zen's own terms permit use "for your own internal use" and with any agent, which is exactly what this is — one person's assistant making a handful of calls per message they sent. Free models carry rolling usage caps that reset within about a day; when a cap wall or a withdrawn model takes a channel down, hongyan treats it as a decision for you, not as noise:

- **Your answer comes first.** The next model in the chain serves the request immediately; triage happens only after the reply is in hand.
- **Temporary failures** (overload, timeouts) earn the channel a two-minute cooldown and nothing else.
- **Cap walls and gone-looking failures bench the channel indefinitely**, alert you at once, and queue an action item so the next digest raises it. Nothing quietly un-disables itself: `use <model>` puts a channel back after you have looked, `status` shows what is benched.

That availability warning still comes from real failures rather than polling — see [It only acts when you tell it to](#it-only-acts-when-you-tell-it-to).

Free tiers rotate, though, and that failure is nastier than it sounds: a model that quietly leaves the free tier turns every answer into a 404 that reads like a broken API key. With chains, the first symptom is not silence but a slower answer from the fallback plus a message saying exactly which channel died and why.

Free models are the interesting constraint, because the natural worry about pointing a language model at a real server is how much you are willing to trust it. **This design means you don't have to.** The safety of the system does not rest on the model being well-behaved, well-aligned, or even competent — which is exactly what makes free-tier models a practical choice rather than a compromise.

## How that works

The model never says *what to run*. It picks a **name** from a list you defined in your own config file, and your code decides what that name actually does.

When the assistant wants to check the server, it replies with something like `{"action": "probe", "name": "disk"}`. It does not write a shell command, and there is nowhere to put one. The code looks up `disk` in a registry you control and runs the command *you* wrote there. A name that isn't in the registry is simply dropped. Same for reading web pages: the model may name a bare hostname, or one of the URLs a search actually returned during this same request — never a URL it composed itself.

So the model's output is only ever a menu selection. It has no shell, no filesystem access, no write path, and no credentials in reach.

The useful consequence is that this survives a bad model, a jailbreak buried in a fetched web page, and a prompt-injection attempt in an image caption — because at no point is model output interpreted as an instruction to the machine.

### It only acts when you tell it to

hongyan does nothing on its own initiative. Every message it sends and every request it makes to a model provider is the direct result of you texting it — there is no polling, no background chatter, no unattended traffic against anyone else's service. The only scheduled job is local: a watchdog that checks whether its own processes are alive.

This is deliberate beyond good manners. Signal's terms forbid automated messaging, and the design agrees with them: nothing periodic — not the monthly review, not the queue digest, not anything else — is ever *sent* on a timer. When one comes due it waits in a local file, rides along as a second text after your next answered message ("by the way, it's time for the monthly review — reply yes to run it"), and goes out only after you say yes. Ignored offers go quiet on their own; declining defers a full cycle. You can also skip the dance entirely: type `review` or "do the monthly review" and it just runs — asking by name *is* the permission.

Even the model-availability warning works this way. Rather than polling to ask whether a model still exists, it notices when a real request fails and tells you then, which is both simpler and the moment it first matters.

The one exception is opt-in and off by default: `roster_check` lets the monthly review ask your provider for its current model list. Turn it on only if that provider's terms permit programmatic clients.

### Permission tiers

| Tier | What | How it's reached |
|---|---|---|
| T1 | Read-only checks — disk, services, certificates, boot history, memory | Typed command, a synonym, or the assistant naming a probe |
| T2 | Reversible actions — restart an allowlisted service, re-run an allowlisted job, clear a queued item | **Typed exactly, by you.** A model may never route here |
| T3 | Anything destructive or outward-facing | **Never allowed** |

Free text is answered or saved for later — never executed. A message is acted on only when it names an allowlisted command.

This matters more than it sounds. In testing, asked to "run the updates", the guardrails held perfectly and nothing executed — but the model *said* "I'll run the upgrades now", and when asked directly, "Yes, they ran." Claiming a privileged action it structurally cannot perform is worse than refusing, because you would believe a server had been patched. The fix wasn't a politer prompt: a deterministic check now recognises an action request and injects a plain statement of fact into the model's context saying nothing was run, rather than trusting it to remember its own limits.

### Who's allowed to talk to it

Authorisation is by **ACI** — Signal's own internal account identifier, a UUID that Signal validates cryptographically and that cannot be spoofed by someone spoofing a phone number. Messages from any other sender are dropped without being parsed. Phone numbers appear in the config only as display attributes and never authorise anything.

Signal delivers messages sealed-sender, meaning the sender is hidden from the text output entirely — so the JSON API is the only place the real ACI can be read.

It only ever messages its owner. There is no path by which it contacts anyone else: the recipient is fixed in config, nothing reachable by a model can change it, and it never initiates a conversation with a third party or sends anything unsolicited. That is worth stating plainly, because an assistant that replies automatically is the sort of thing messaging platforms reasonably restrict — the rules exist to stop bulk and unsolicited traffic to strangers, and this is a private assistant talking to one consenting person, its owner.

## What it does

- **Works out its own next step.** Up to five read-only steps per question: search, open a page, probe the server, check the weather, then answer.
- **Reads photos.** An image is described first, and that description feeds the normal pipeline — so "how much is this worth?" gets both a look and a search, rather than a guess from the caption alone.
- **Understands replies.** Reply to any earlier message and that conversation becomes the context, overriding the automatic follow-up detection. It confirms by replying as a Signal quote, so a wrong match is visible immediately instead of producing a baffling answer.
- **Tracks follow-ups.** A separate step decides which earlier exchanges matter and rewrites your message as a standalone question before anything is looked up, so "what about the plural?" gets researched properly.
- **Keeps a queue.** Anything that's a task rather than a question is saved and offered back the next time you text it — "3 things have been waiting since 2d ago, reply yes for the list" — until you clear it.
- **Looks after itself.** A watchdog restarts what dies, escalates over Signal when restarts keep failing, tells you how long it was down once it recovers, and warns you if a model it depends on has left the catalogue.
- **Reviews itself monthly, on your say-so.** When the month rolls over it waits; your next message gets an offer, and only a yes sends anything — or type "do the monthly review" to skip the ceremony. It diffs the free-model roster, flags capability gaps against how it's wired, and summarises the defects it logged — counted by kind, so a recurring fault is distinguishable from a one-off. The review is deliberately plain code with no model call, because something that exists to catch the assistant misbehaving shouldn't depend on the assistant behaving.
- **Never goes quiet.** Every path that drops a message — too old, rate limited, kill switch, unrecognised quote — says so. An unexplained non-reply is indistinguishable from a crash.

## What it won't do

It will not run commands, install packages, restart system services, edit files, or message anyone else. Asked to, it says so plainly.

## Requirements

- A Linux server with **256 MB of free RAM** and **500 MB of disk**. Measured on a live install: signal-cli's daemon holds about 137 MB resident and the listener about 26 MB, so roughly 165 MB in normal operation. On disk, signal-cli and its bundled Java runtime are about 356 MB, account state around 9 MB, and this repository under 1 MB. Received photos accumulate in the attachment store and are pruned automatically after 14 days.
- Python 3 (standard library only — no pip install) and [signal-cli](https://github.com/AsamK/signal-cli).
- **A second phone number for the bot.** The assistant gets its own Signal account, separate from yours — a free VoIP number works. There is a way to avoid this using Note to Self, but you should read [Note to Self, and why it is not the default](#note-to-self-and-why-it-is-not-the-default) before reaching for it.
- An API key for any OpenAI-compatible inference endpoint.

## Note to Self, and why it is not the default

Signal already gives you a private thread with yourself, so it is reasonable to ask why hongyan needs a second phone number at all. It doesn't — `transport: "note_to_self"` is supported, and you text your own Note to Self thread instead. Replies come back there, and they do notify: hongyan sends a real message to your account rather than a silent sync message, which is the difference between `--notify-self` and `--note-to-self` in signal-cli.

**But understand what it costs before you choose it.**

To read your Note to Self, hongyan has to be **linked as a device on your own Signal account** — the same mechanism as Signal Desktop. That is a fundamentally different security position from a separate bot account:

> ⚠️ **A linked device receives a copy of every conversation you have.** Not just Note to Self — everything you send and everything you receive, in every chat, from the moment it is linked. And it can send as you, to anyone in your contacts.
>
> **If this server is ever compromised, your entire Signal identity goes with it.** An attacker reads your private conversations and messages your contacts while appearing to be you. With a separate bot account, the worst case is a throwaway number that talks only to you.
>
> Your server is a machine on the internet running a program that fetches web pages and calls a third-party API. Weigh that honestly against putting your personal messaging account on it.

hongyan does what it can to limit the exposure: the very first thing it does with any message is check that it is a note from you to yourself, and anything else is dropped before the text is read, logged, or passed anywhere. That filter is covered by tests. But it is a filter applied *after* the messages have already arrived on the machine — the data is there either way, and no amount of care in this program changes what a linked device is.

If you use it anyway:

- Set `transport` to `note_to_self` and leave `bot_number` empty.
- Link with `signal-cli link -n hongyan`, then scan the QR code from Signal on your phone.
- The link shows up in Signal under **Settings → Linked Devices**. Revoke it there the moment the server is retired, sold, or you suspect it has been touched.
- Do not link the same account from a second machine as well. One account driven from two places corrupts the session state.

The separate bot account remains the default because a compromised server should cost you a spare phone number, not your messaging history.

## Install

One command, on the server:

```sh
curl -fsSL https://raw.githubusercontent.com/chkiss/hongyan/main/install.sh | bash
```

It fetches the code to `~/hongyan`, asks for your ACI, numbers and API key, writes the config, links the commands into `~/.local/bin`, installs the cron entries and runs the tests. Re-running it is safe: it never overwrites a config without asking and never duplicates a cron line.

It checks the *format* of what you type — a UUID that is a UUID, phone numbers with country codes, a bot number that differs from yours — but it cannot tell whether the ACI is really yours or the key works, and it says so. That matters because a wrong ACI fails silently by design: unauthorised messages are dropped without a reply, so the symptom is a bot that ignores you. Text it `status`, and if nothing comes back, `tail ~/.config/hongyan/audit.log` — a `rejected` line means the ACI is wrong.

Then `hongyan-supervise` to start.

Nothing here needs systemd, deliberately: user timers need lingering enabled, which needs root, and this is designed to run as an ordinary unprivileged account.

### One device or two

**One device** is the default: everything runs on the server, including a monthly self-review that summarises the defects it logged that month — counted by kind, so a recurring fault stands out from a one-off. It reads its own log and nothing else, unless you opt into `roster_check`. The review is never sent on a schedule: it is offered after your next message and delivered only when you reply yes. Nothing else is required.

**Two devices** adds a second machine that runs a richer monthly review with a full agent — one with the memory and tooling to judge whether a new model actually *suits* the job, propose concrete wiring changes, and apply them once you approve.

Set the server up as above, then on the review host — one command again, and no clone:

```sh
curl -fsSL https://raw.githubusercontent.com/chkiss/hongyan/main/install-review-host.sh | bash
```

It checks it can actually reach the server, points the server's `monthly_review` at `remote` so you don't get two reports that disagree, and writes a brief for the review agent to follow.

The review host reaches the server over SSH. The server never needs to reach back, so it can sit behind NAT with no inbound access, and approvals cross the gap by keyword: the reviewer writes the words it will accept, the listener watches for them in your replies, and the reviewer polls for the match.

Everything the review does is read-only until you reply `approve`.

## Configuring it for your machine

Everything host-specific lives in the config: the machine's label, its home directory, which services exist and how each is checked, plus any extra commands and probes you want to add. There is no separate "example" copy of this code — this repository is what runs.

```jsonc
"services": {
  "nginx":     {"type": "system"},
  "syncthing": {"type": "user", "unit": "syncthing"},
  "immich":    {"type": "port", "port": 2283}
}
```

`type` matters more than it looks. A user service checked as a system service always reports inactive, so a perfectly healthy service appears dead — and anything running in a container may have no service entry at all, only a listening port.

Adding a new check is a config edit, not a code change:

```jsonc
"custom_probes": {
  "backups": {"desc": "last backup result", "command": "tail -n 3 ~/backup.log"}
}
```

The assistant can now answer questions about your backups by naming `backups`. The command text is yours, from your own config file — as trusted as the rest of your code, and still never written by a model.

## Tests

```sh
python3 tests/test_listener.py
```

No network, no Signal account, no model calls — pure logic and stubbed loops. Every test names the specific defect it prevents, because most of them are regressions that reached production first. The one that took longest to find was silent: a file lookup that returned "nothing found, no error", which the caller read as "no image was attached", so the assistant spent a month confidently telling its owner there was no photo in messages that plainly had one. Nothing appeared in the logs, because nothing thought anything had gone wrong. A lookup that misses now returns an error, and the tests hold that line.

## License

MIT
