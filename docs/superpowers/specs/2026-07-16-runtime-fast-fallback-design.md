---
title: Fast, diagnosable WebView2 runtime fallback
status: approved
date: 2026-07-16
---

# Fast, diagnosable WebView2 runtime fallback

## Context

The 2026-07-14 hybrid acquisition spent 92.3 seconds attempting the optional
Store 8 runtime supplement before correctly continuing offline. Forty
`/json/list` requests each timed out. The current loop gives every request a
two-second timeout, silently discards the failure, then sleeps for 250 ms until
the fixed 90-second deadline. It never reached CDP or the injected serializer.

The offline acquisition, decryption, unification, validation, and archive
completed successfully. The change must therefore speed up a failed optional
supplement without changing the authoritative offline evidence path.

## Goals

- Default hybrid runs fail the unavailable-runtime path in at most 20 seconds
  after launch, with a precise, non-secret diagnostic.
- Keep a `-DeepRuntime` / `--deep-runtime` escape hatch with the existing
  90-second budget for slow or unusual machines.
- Use condition-based process and DevTools readiness checks; do not add an
  arbitrary fixed startup sleep.
- Restore the previous WebView2 registry value on every outcome and preserve
  the current offline fallback behavior.
- Make the failure states testable without a real WhatsApp install.

## Non-goals

- Changing Store 8 serialization, CDP evaluation retry behaviour, database
  decryption, IndexedDB extraction, or unified-database semantics.
- Making remote debugging reliable on enterprise devices that forbid it.
- Parallelizing `ccl_chromium_reader` or SQLite writes.

## Design

### CLI and policy

Hybrid and runtime-only mode use a 20-second DevTools readiness budget by
default. `-DeepRuntime` and `--deep-runtime` select the legacy 90-second
budget. The selected budget is included in the command summary and the
runtime-supplement manifest metadata.

### Runtime state machine

`Invoke-WAren6RuntimeStore8Capture` receives the selected readiness budget. It
will:

1. Save and apply the WebView2 debugging-policy value as it does today.
2. Stop existing WhatsApp processes and wait only until their exit condition is
   observed, using a short bounded poll. A timeout is logged distinctly rather
   than silently racing the relaunch.
3. Launch WhatsApp and probe the local DevTools endpoint with a short
   per-request timeout and 250 ms polling interval. The overall budget, not a
   fixed number of retries, controls the wait.
4. Treat a matching `web.whatsapp.com` page in `/json/list` as the readiness
   condition. Only then open CDP and run the existing serializer.

The fast path does not change the existing CDP evaluation retry loop. Once a
page is ready, its yield behaviour remains unchanged.

### Diagnostics and provenance

Every failed readiness attempt is classified without printing raw evidence or
keys. The final exception and runtime-supplement metadata record the elapsed
time, selected budget, and one of: endpoint unreachable, endpoint timeout,
HTTP failure, invalid target payload, no matching WhatsApp page, or WhatsApp
exit timeout. Per-attempt errors are aggregated rather than emitted as dozens
of transcript `TerminatingError` lines.

The code records whether the registry setting was applied and restored, whether
WhatsApp was observed after launch, and the endpoint state. It does not log
command lines, raw HTTP payloads, ODUIDs, keys, cookies, or message data.

### Failure semantics

Any readiness failure remains non-fatal in hybrid acquisition: WAren6 records
the reason, restores the registry setting, then performs the existing offline
copy, decryption, validation, and archive. Runtime-only mode continues to exit
non-zero on failure. The `-DeepRuntime` switch is the compatibility route when
the 20-second default is too short for a particular machine.

## Tests and verification

- Extend the PowerShell runtime source tests to assert the 20-second default,
  90-second deep budget, condition-based polling, explicit diagnostics, and
  registry restoration.
- Add focused regression coverage for an unavailable or non-responsive endpoint
  so a two-second-per-retry loop cannot reappear unnoticed.
- Run the full authoritative Python test suite.
- Manually run the existing WhatsApp Desktop verification checklist on a real
  field machine before release. Confirm both a quick failed fallback and a
  successful runtime supplement.
- Update the performance KB with measured results. The incident path should
  complete its runtime stage within 20 seconds, rather than 92.3 seconds.

## Deferred follow-up

After this change is measured, profile cold Python bootstrap and the
34-second IndexedDB extraction separately. Those are material but independent
from the proven runtime timeout defect; bundling them into this change would
obscure which intervention improved the field run.
