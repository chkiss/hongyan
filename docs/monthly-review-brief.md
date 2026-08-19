# Monthly review brief (two-device setup)

Register this with your agent runner on a monthly schedule. It assumes SSH access to the server as `SSH_TARGET` and no ability for the server to reach back — the bridge is one-way.

The server can do a version of this review by itself (`hongyan-watchdog --monthly`), and does when `monthly_review` is `local`. This brief exists because an agent with real tooling can do three things the server's own version cannot: judge whether a new model is actually *suited* to the job rather than merely present, propose concrete wiring changes, and apply them once approved.

## 1. Roster and capability gaps

Fetch the live roster:

```sh
curl -s --max-time 15 "https://portal.nousresearch.com/api/nous/recommended-models" -H "Accept: application/json"
```

Compare `freeRecommendedModels`, `freeRecommendedVisionModel` and `freeRecommendedCompactionModel` against the snapshot the server keeps at `~/.config/hongyan/roster.json`.

For each model in the free roster, compare `inputModalities`, `outputModalities`, `isVisionModel` and `contextLength` against what the listener is wired to handle (`config.json` plus `hongyan_listener.py`). Propose wiring changes **only where a real gap exists**; if there is none, say so in one line.

Judge suitability, not just availability. A model can be excellent and wrong for this job — one tuned for agentic coding is not the one you want answering questions about grammar or summarising a news page. Name the intended role when you propose a switch.

## 2. Defects in the log

Read `~/.config/hongyan/audit.log` **and** its rotated archive `audit.log.1` — the live file holds only the most recent ~800 lines, so a month is usually split across both.

Start by grepping for `FAIL:`. The listener tags every defect that way (`FAIL:vision`, `FAIL:quote_unresolved`, `FAIL:model_error`, `FAIL:history_truncated`, …). Anything without that tag is ordinary routing. If `FAIL:` returns nothing, say the log is clean — do not go hunting through normal lines for something to report.

Beware the inverse: an empty grep is only meaningful if the log is being written at all. Check the file's mtime is recent before calling it clean. Two real bugs survived for weeks precisely because they failed silently and left no line.

Look only for genuine defects — unhandled errors, repeated failures of one kind, missing references, structural wiring bugs. Do **not** flag transient upstream errors (503/403/timeouts from the model provider) or normal behaviour (queued messages, throttle cooldowns, routing hits). Propose at most one concrete fix, with a one-line rationale.

Do not overfit. Something that appeared once and never recurred is a one-off, not a pattern.

## 3. Report

Send one Signal message via the server:

```sh
ssh SSH_TARGET '~/.local/bin/hongyan-send.py' <<< "$MESSAGE"
```

Format: a header line, one bullet per proposed change, and a closing approval line. If a category found nothing, say so in one line rather than omitting it. Keep it under eight lines; if it needs more, write the detail somewhere durable and reference it.

End with: `Reply 'approve' to apply all proposed changes, 'acknowledge' if nothing to do, or describe the failure if I missed something.`

## 4. Approval

The server has no route back to this machine, so replies are matched by keyword and polled for.

1. Before sending, write `~/.config/hongyan/monthly-reply-keywords-YYYY-MM-DD.txt` on the server — one keyword per line: `approve`, `acknowledge`, plus any custom tokens used in that month's message.
2. The listener watches owner messages for those keywords and writes `~/.config/hongyan/monthly-reply-YYYY-MM-DD.txt` when one matches. This is idempotent.
3. Poll for that file: every 60 seconds for 30 minutes, then hourly for 24 hours. On a match, read it and act. On timeout, log that no reply arrived and stop.

Apply changes only on an explicit `approve`. Everything up to that point is read-only.
