---
title: "ADR-005: Fast, diagnosable WebView2 runtime fallback"
tags: [adr, runtime, performance, reliability]
status: Accepted
date: 2026-07-16
---

# ADR-005: Fast, diagnosable WebView2 runtime fallback

## Status

Accepted (2026-07-16).

## Context

The 2026-07-14 hybrid acquisition spent 92.3 seconds trying to obtain the
optional Store 8 runtime supplement, then completed offline successfully. The
failure was before CDP and the injected serializer: forty loopback
`/json/list` requests timed out, each failure was discarded, and the fixed
90-second readiness deadline expired.

The offline acquisition and unification path is authoritative. Runtime capture
must remain a best-effort supplement, so an unavailable WebView2 debugger must
not dominate field acquisition time or obscure the reason for the fallback.

## Decision

- Use a 20-second DevTools readiness budget by default in hybrid and
  runtime-only mode. `-DeepRuntime` / `--deep-runtime` retains the legacy
  90-second budget for slow or unusual machines.
- Stop existing WhatsApp processes and wait for their observed exit with a
  five-second bounded poll before requesting a relaunch. Report a distinct
  `whatsapp_exit_timeout` rather than racing the relaunch.
- Probe only the loopback DevTools endpoint with a no-proxy `HttpWebRequest`, a
  500 ms maximum per-probe timeout, and an overall deadline that caps the final
  probe and sleep. A matching `web.whatsapp.com` page is the readiness
  condition.
- Surface only safe readiness metadata in the acquisition manifest: selected
  budget, elapsed time, attempt count, HTTP status when available, registry
  apply/restore state, and a classified failure. Never persist target payloads,
  debugger URLs, cookies, keys, or message data.
- Preserve registry restoration in `finally` and the existing hybrid fallback:
  runtime failure warns and continues offline; runtime-only exits non-zero.

## Consequences

**Positive:** an unavailable runtime now consumes roughly 20 seconds after
launch instead of the incident's 92.3 seconds, and its failure is useful for
triage without exposing evidence. The default does not change the serializer,
database extraction, merge, or validation behavior.

**Negative:** a very slow but otherwise healthy runtime may need an explicit
`--deep-runtime` retry. A process that will not exit is reported quickly rather
than being force-raced into a potentially ambiguous relaunch. Real WhatsApp
Desktop success still requires field verification; synthetic tests cover only
the local readiness state machine.

## Alternatives considered

1. **Keep the fixed 90-second loop.** Rejected because the incident proved it
   is a large, silent delay in an optional path.
2. **Keep two-second requests but reduce retry count.** Rejected because a
   stalled local endpoint would still waste two seconds per attempt and could
   overrun the intended budget.
3. **Use a fixed post-launch sleep.** Rejected because it slows healthy starts
   and does not identify an unavailable debugger.

## References

- [[adr/ADR-002-store8-hybrid-recovery]] — runtime capture remains supplemental.
- [[perf/Bottlenecks]] — incident-proven runtime timeout cost.
- [[compat/WhatsApp-version-compat]] — WebView2 and package-version risks.
- `docs/superpowers/specs/2026-07-16-runtime-fast-fallback-design.md` — approved implementation design.
- `tests/test_waren6_runtime_probe_ps1.py` — bounded loopback timeout coverage.
