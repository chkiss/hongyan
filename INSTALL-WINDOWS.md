# Running hongyan on Windows

hongyan is a personal Signal bot that watches a machine and acts on it. On
Windows it speaks fluent PowerShell: it can report disk/memory/uptime, count
system error events, restart services, and reboot the box — which makes a
media-server box (Plex et al.) its natural home.

## Prerequisites

1. **Python 3.10+** — python.org installer, "Add to PATH" ticked.
2. **Java 21+** — Temurin from adoptium.net (signal-cli's JVM build needs it;
   the Linux native binary needs no Java, Windows does).
3. **signal-cli** — download the `signal-cli-X.Y.Z-Windows-x86_64.zip` from
   the releases page (or the JVM tarball), unzip to e.g. `C:\signal-cli`.

## 1. Link the Signal account

signal-cli needs its own number acting as a *linked device* on your phone's
account, or a standalone registered number. The simple path:

```
cd C:\signal-cli
java -jar signal-cli.jar link -n "hongyan-windows"
```

Scan the QR / open the `tsdevice:` URI from your phone (Signal → Settings →
Linked Devices). Note the number it prints — that is `bot_number`.

## 2. Start the daemon

```
java -jar signal-cli.jar -a +1BOTNUMBER daemon --tcp 127.0.0.1:7583 --receive-mode on-connection --no-receive-stdout
```

TCP, not a unix socket — that is what the Windows port speaks. Keep this
window open (or register a scheduled task for it, step 5).

## 3. Configure hongyan

Copy `config.example.windows.json` to
`%USERPROFILE%\.config\hongyan\config.json` and fill in:

- `bot_number`, `owner_number` — the two phone numbers
- `owner_aci` — text the bot once from your phone; it will reject you and log
  your ACI in the audit line (`rejected  aci=...`). Paste that UUID in.
- `socket` stays `127.0.0.1:7583`
- `allowed_units` + `services` — your restartable services. Find Plex's exact
  service name with `powershell Get-Service *plex*`.

## 4. Run the listener

```
python hongyan_listener.py
```

Text it `status`. You should get uptime, disk, memory, failed services.

## 5. Make it survive reboots (and permit reboots)

Service restarts and `shutdown /r` need elevation. Create two scheduled
tasks (as Administrator):

```
schtasks /create /tn "hongyan daemon" /sc onstart /ru YOU /rl HIGHEST /tr "java -jar C:\signal-cli\signal-cli.jar -a +1BOTNUMBER daemon --tcp 127.0.0.1:7583 --receive-mode on-connection --no-receive-stdout"
schtasks /create /tn "hongyan listener" /sc onstart /ru YOU /rl HIGHEST /tr "python C:\path\to\hongyan_listener.py"
```

`/rl HIGHEST` is the piece that makes "restart plex" and "reboot box" actually
work instead of failing with access denied.

## What works on Windows vs Linux

| Capability | Windows | Linux |
|---|---|---|
| Conversation, agent, memory, queue, vision, STT | yes | yes |
| status / disk / memory / uptime / error_count probes | yes (PowerShell) | yes |
| Service restart via `allowed_units` | yes (elevated) | user units |
| Full-box reboot | yes (`shutdown /r`, 10s abort window) | not built in |
| journalctl/systemctl/certbot probes, cron inspection | absent | yes |

## Security notes

- The daemon binds TCP on **127.0.0.1 only** — do not expose 7583.
- The owner ACI in config is the sole key: anyone who can text from your
  number owns the box. Treat `config.json` accordingly.
- `reboot box` is typed-exact with a 10-second abort window (`shutdown /a`).
