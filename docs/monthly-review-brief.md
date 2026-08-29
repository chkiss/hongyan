# Monthly review brief (two-device setup)

Register this with your agent runner on a monthly schedule. It assumes SSH access to the server as `SSH_TARGET` and no ability for the server to reach back — the bridge is one-way.

The server can do a version of this review by itself (offered in conversation when `monthly_review` is `local`). This brief exists because an agent with real tooling can do three things the server's own version cannot: judge whether a new model is actually *suited* to the job rather than merely present, propose concrete wiring changes, and apply them once approved.

## 0. When to run

Only after the owner has messaged the server this month. Check the newest `YYYY-MM` prefix in `~/.local/state/hongyan/audit.log` over SSH: if no entry is dated this month, the month has produced no conversation and there is nothing to review yet — exit quietly. No scheduled send may ever precede a message the owner sent.

## 1. Roster and capability gaps

Fetch the live catalogue:

```sh
curl -s --max-time 15 "https://opencode.ai/zen/v1/models" -H "Accept: application/json"
```

Compare against what the server actually runs: `text_chain` and `vision_chain` in `~/.config/hongyan/config.json`. Free identifiers end in `-free`; the stealth previews are `x-preview-f-free` (Ox Alpha) and `big-pickle`. Pricing lives at https://opencode.ai/zen.

For each configured model check: presence in the catalogue, cost (Free vs paid), context length, and image-input capability — every `vision_chain` entry must accept images or photo questions break. Judge suitability, not just availability: a model tuned for agentic coding is not the one you want answering grammar questions. Propose wiring changes **only where a real gap exists**; if none, say so in one line.

Also read `~/.local/state/hongyan/model_state.json`: each benched channel with `"until": null` is disabled awaiting a human decision — recurring bench patterns (`FAIL:model_benched` in the log) belong in the report. Queue items of kind `action` are unresolved decisions the owner has been promised about.

## 2. Defects in the log

Read `~/.local/state/hongyan/audit.log` **and** its rotated archive `audit.log.1` — the live file holds only the most recent ~800 lines, so a month is usually split across both.

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

1. Before sending, write `~/.local/state/hongyan/monthly-reply-keywords-YYYY-MM-DD.txt` on the server — one keyword per line: `approve`, `acknowledge`, plus any custom tokens used in that month's message.
2. The listener watches owner messages for those keywords and writes `~/.local/state/hongyan/monthly-reply-YYYY-MM-DD.txt` when one matches. This is idempotent.
3. Poll for that file: every 60 seconds for 30 minutes, then hourly for 24 hours. On a match, read it and act. On timeout, log that no reply arrived and stop.

Apply changes only on an explicit `approve`. Everything up to that point is read-only.
