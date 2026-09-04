---
title: Mistakes not to repeat
tags: [footguns, warnings]
---

# Mistakes not to repeat

Short-form. Each entry: symptom, cause, fix, why-it-happens-again.

## 1. Do not re-parse WAL frames manually as the primary strategy

**Symptom:** subtle B-tree corruption after a rebuild on newer WhatsApp Desktop.
**Cause:** WhatsApp v2.3000+ keeps most data in the WAL and never checkpoints. Manually stitching page frames drops metadata SQLite's own WAL reader would have applied.
**Fix:** `_apply_wal_and_open` (waren6.py:1993) already copies `.db + .db-wal + .db-shm` to a temp dir and lets SQLite handle it natively. Manual apply is ONLY the fallback path when the native path fails a schema sanity check.
**Why it repeats:** convenience — the manual apply "just works" in test fixtures. Do not remove the native-first branch.

## 2. Do not silently drop rows we cannot fully classify

**Symptom:** `unified_whatsapp.db` looks clean but is missing evidence that was present in the source.
**Cause:** old approach filtered rows without recovered text.
**Fix:** keep the row with a `body_status` label — `missing`, `opaque_unresolved`, `encrypted_body`, etc. Reader distinguishes; a forensic reviewer needs the row to exist.
**Why it repeats:** developer aesthetic of "clean output". WAren6 is loss-prevention, not summarisation.

## 3. Do not skip the ODUID cross-check when using `--id`

**Symptom:** decryption fails on evidence collected from a different Windows profile with a plausible-looking ODUID.
**Cause:** ODUID is a per-Windows-account fingerprint; a wrong hex string doesn't error, it just derives the wrong key and produces garbage.
**Fix:** the PS1 doctor mode validates ODUID against the local machine when possible; `--show-secret-id` guards raw ODUID printing.
**Why it repeats:** the failure mode looks like corruption, not like a wrong key. Add richer diagnostics if this bites again.

## 4. Do not assume the runtime capture path is reliable

**Symptom:** hybrid mode reports no `runtime_store8_messages.jsonl` on some machines even with a logged-in WhatsApp.
**Cause:** the WebView2 registry override (`waren6.ps1:3140`) is per-user, not per-machine. It's cleared by MDM-managed devices. Some corporate images strip it silently.
**Fix:** treat runtime capture as best-effort. The offline pipeline must produce a complete `unified_whatsapp.db` on its own; runtime is a supplement. Never regress that invariant.

## 5. Do not remove the `WAren6_unify_later.txt` fallback

**Symptom:** operator on an air-gapped box with no Python has an archive but no unified DB and no path forward.
**Cause:** the fallback text file documents the exact command to run later.
**Fix:** whenever `-a` mode is used without Python available, write `WAren6_unify_later.txt` beside the archive. Never suppress it.

## 6. Do not amend an existing commit for "small doc updates" during a release

**Symptom:** two Field Kit builds with the same tag produce different zips.
**Cause:** amending re-signs the tag.
**Fix:** always cut a new commit. Field Kit release automation triggers off tag SHA.

## 7. Do not hard-code path separators or use `\\` in Python

**Symptom:** POSIX-run tests fail on Windows (or vice-versa).
**Cause:** mixing `str.join('\\')` in one place and `pathlib` in another.
**Fix:** always `pathlib.Path`. When emitting a case-relative path into the DB, use forward slashes so Reader can render it identically on any platform.

## 8. Do not print secrets in verbose mode

**Symptom:** operator pastes a `-v` log into a bug report; it contains the raw ODUID or decrypted key material.
**Cause:** debug prints of the crypto context.
**Fix:** `VERBOSE_CONSOLE = False` by default. The Store 8 crypto profile emits only lengths and SHA-256, never key material.

## 9. Do not let an optional runtime endpoint monopolize acquisition time

**Symptom:** a hybrid run spends roughly 90 seconds in runtime capture, then succeeds offline with no useful reason for the delay.
**Cause:** a fixed readiness deadline combined with long per-request timeouts and swallowed loopback DevTools errors.
**Fix:** use the bounded `Invoke-WAren6DevToolsProbe` / `Wait-WAren6DevToolsPage` state machine: 20 seconds by default, short deadline-capped probes, classified diagnostics, and `--deep-runtime` only for a conscious 90-second retry.
**Why it repeats:** treating the live runtime as mandatory. It is a supplement; preserve and prioritize the offline evidence path.

## 10. Do not infer zstd write support from tar version output

**Symptom:** target-side acquisition succeeds until archive creation, then `tar.exe --zstd` fails because it cannot launch `zstd`.
**Cause:** Windows BSD tar can accept `--zstd --version` while still depending on an external `zstd.exe` for actual compression.
**Fix:** prove support with a tiny create-and-readback probe; use the verified ZIP fallback otherwise.
**Why it repeats:** version output looks like a capability declaration, but it is not an end-to-end archive test.

## 11. Do not use a foreign key for a logical, non-unique message key

**Symptom:** SQLite integrity checks fail with `foreign key mismatch` even though the database was built successfully.
**Cause:** WhatsApp source variants can legitimately share `messages.msg_key`; it is not a candidate key.
**Fix:** retain `msg_key` as an indexed correlation field in child evidence tables, without a SQLite foreign-key constraint.
**Why it repeats:** the field name looks like an identifier, but forensic variant preservation intentionally changes its cardinality.
