# signal-assistant

A read-only assistant for your own Linux server, reachable over Signal, running entirely on free-tier language models.

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

The whole thing runs on the free tier of [Nous Research's inference API](https://inference-api.nousresearch.com/v1) — the Hermes ecosystem — using an OpenAI-compatible endpoint and a static API key. Three models do different jobs:

| Job | Model | Why |
|---|---|---|
| Routing and planning | `upstage/solar-pro4:free` | Fast, cheap to call repeatedly, reasoning disabled |
| Answering | `tencent/hy3:free` | Strong reasoning; worth the extra latency |
| Vision | `stepfun/step-3.7-flash:free` | The only free model here that accepts images |

Any OpenAI-compatible endpoint works — set `api_base` and `key_file` in the config and name whichever models you like.

Free models are the interesting constraint, because the natural worry about pointing a language model at a real server is how much you are willing to trust it. **This design means you don't have to.** The safety of the system does not rest on the model being well-behaved, well-aligned, or even competent — which is exactly what makes free-tier models a practical choice rather than a compromise.

## How that works

The model never says *what to run*. It picks a **name** from a list you defined in your own config file, and your code decides what that name actually does.

When the assistant wants to check the server, it replies with something like `{"action": "probe", "name": "disk"}`. It does not write a shell command, and there is nowhere to put one. The code looks up `disk` in a registry you control and runs the command *you* wrote there. A name that isn't in the registry is simply dropped. Same for reading web pages: the model may name a bare hostname, or one of the URLs a search actually returned during this same request — never a URL it composed itself.

So the model's output is only ever a menu selection. It has no shell, no filesystem access, no write path, and no credentials in reach.

The useful consequence is that this survives a bad model, a jailbreak buried in a fetched web page, and a prompt-injection attempt in an image caption — because at no point is model output interpreted as an instruction to the machine.

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

## What it does

- **Works out its own next step.** Up to five read-only steps per question: search, open a page, probe the server, check the weather, then answer.
- **Reads photos.** An image is described first, and that description feeds the normal pipeline — so "how much is this worth?" gets both a look and a search, rather than a guess from the caption alone.
- **Understands replies.** Reply to any earlier message and that conversation becomes the context, overriding the automatic follow-up detection. It confirms by replying as a Signal quote, so a wrong match is visible immediately instead of producing a baffling answer.
- **Tracks follow-ups.** A separate step decides which earlier exchanges matter and rewrites your message as a standalone question before anything is looked up, so "what about the plural?" gets researched properly.
- **Keeps a queue.** Anything that's a task rather than a question is saved and resurfaced in a morning summary until you clear it.
- **Looks after itself.** A watchdog restarts what dies, escalates over Signal when restarts keep failing, and tells you how long it was down once it recovers.
- **Never goes quiet.** Every path that drops a message — too old, rate limited, kill switch, unrecognised quote — says so. An unexplained non-reply is indistinguishable from a crash.

## What it won't do

It will not run commands, install packages, restart system services, edit files, or message anyone else. Asked to, it says so plainly.

## Requirements

- A Linux server, Python 3, and [signal-cli](https://github.com/AsamK/signal-cli).
- **A second phone number for the bot.** The assistant needs its own Signal account, separate from yours — a free VoIP number works. This isn't incidental: sending yourself a message via Signal's "note to self" produces no notification, so a bot messaging your own account would be silent.
- An API key for any OpenAI-compatible inference endpoint.

## Install

```sh
git clone https://github.com/YOURNAME/signal-assistant
cd signal-assistant
cp config.example.json ~/.config/signal-listener/config.json
$EDITOR ~/.config/signal-listener/config.json      # your ACI, models, services
printf '%s' "$YOUR_API_KEY" > ~/.config/signal-listener/nous.key
chmod 600 ~/.config/signal-listener/nous.key
./signal-supervise                                  # starts the daemon and listener
```

Then add to cron:

```cron
@reboot sleep 30 && /path/to/signal-supervise
*/10 * * * * /path/to/signal-watchdog --restart
23 8 * * *  /path/to/signal-watchdog --daily
```

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
