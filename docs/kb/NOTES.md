---
title: Running notes
tags: [scratchpad]
---

# NOTES

Rolling scratchpad. Trim quarterly. Datestamp each entry.

## 2026-07-28 — Logical message-key schema integrity

- The first live unified DB on `ANIRBANDEYPC` passed `integrity_check`, `quick_check`, WAren6 validation, and manifest verification, but `foreign_key_check` exposed invalid schema relationships from child evidence tables to non-unique `messages.msg_key`.
- `msg_key` is deliberately non-unique because same-key variants are preserved as evidence. Removed those invalid foreign keys while retaining the child columns and indexes, then scheduled a final live no-archive verification to regenerate the database and manifest from the corrected schema. See [[adr/ADR-007-logical-message-key-relations]].

## 2026-07-28 — Archive capability fallback on Windows BSD tar

- Live `ANIRBANDEYPC` acquisition recovered the client key through the schema-agnostic WAL scan and completed decryption, but its Windows 11 BSD tar failed at `tar.exe --zstd` because external `zstd.exe` was absent.
- Replaced the version-only zstd check with a temporary create-and-readback probe and retained the verified ZIP fallback. Added `--no-archive` for a live acquisition/unification verification run that keeps the case folder and rejects Telegram/archive-only flags.
- Telegram remains CLI-only: `-tg <token> -cid <chat-id>`; its verified splitting and recombination flow is unchanged. See [[adr/ADR-006-archive-capability-fallback]].

## 2026-07-16 — Runtime DevTools fast fallback

- The 2026-07-14 field log proved an unavailable WebView2 DevTools endpoint consumed 92.3 seconds before the healthy offline path continued. The problem was the fixed 90-second loop and silent two-second HTTP timeouts, not IndexedDB or Store 8 parsing.
- Default hybrid/runtime-only readiness is now 20 seconds, with `--deep-runtime` retaining the prior 90-second budget for a deliberately chosen slow-machine retry. Probes are loopback-only, short, deadline-capped, and classified without persisting raw target data.
- Added a five-second observed WhatsApp-exit guard before relaunch plus safe manifest metadata for readiness and registry restore state. See [[adr/ADR-005-runtime-fast-fallback]], [[perf/Bottlenecks]], and [[compat/WhatsApp-version-compat]].
- Synthetic PowerShell coverage includes a local endpoint that accepts TCP and never responds; real WhatsApp Desktop success and slow-start field validation remain manual-release checks.

## 2026-07-04 — Initial audit for perf + newer-WA compatibility

- Graphify seeded: 1041 nodes / 2522 edges / 53 communities. See `graphify-out/GRAPH_REPORT.md`.
- Bottleneck audit landed in [[perf/Bottlenecks]]. Top 6 hot paths ranked with line refs.
- Version-fragile assumptions listed in [[compat/WhatsApp-version-compat]]. Only one truly hard-coded package family name (`waren6.ps1:2928`), and even that path is a fallback launcher — the acquisition side uses `Get-AppxPackage`.
- Zero concurrency in `waren6.py` (grep `ThreadPool|multiprocessing|asyncio|threading.` returned no matches). Biggest single lever for slower/older evidence machines.
- The three known reliability risks under newer WhatsApp Desktop:
  1. WAL-only checkpointing (v2.3000+) — `_apply_wal_and_open` already handles this. See `waren6.py:1993`.
  2. Store 8 opaque `_data` rows requiring WebWA network salt — hybrid runtime path covers many.
  3. Runtime capture depends on injecting a JS expression via WebView2 DevTools; if WhatsApp's internal store/module names change, the expression in `Get-WAren6RuntimeExpression` breaks silently.

## 2026-07-07 -- Optimization sprint 2 + CRITICAL WA schema fix

Landed after a multi-agent research workflow that mapped the unify pipeline stage-by-stage and cross-referenced against SQLite/LevelDB/HKDF background research. All changes preserve extraction yield; all 104 tests pass.

**Field incident (highest priority):** report from `ANIRBANDEYPC` (Win11 Build 22000) showed the acquisition failing with `CRITICAL: No client keys found in session.dec.db-wal`. Root cause: WA Desktop had checkpointed the WAL into `session.dec.db` (or the session table changed shape entirely), so the legacy 3-byte-header byte scanner returned nothing. Fixed with schema-agnostic Tier 2 fallback (see [[adr/ADR-004-session-key-schema-agnostic]]).

**Code changes (waren6.py):**

- HKDF-SHA256 output memoization keyed by `(ikm, salt, info, length)` with bounded (`cap=4096`) FIFO cache. `algorithms.AES(key)` object cache (`cap=512`) too. Honest speedup: 2-5x on the Store 8 opaque stage when triggered (the earlier "25-75x" claim was HKDF-call-only, not stage-wide -- Cipher-object allocation dominates end-to-end).
- `--fast-salt-hunt` CLI flag: opt-in early exit when >=3 validated candidates AND 32 consecutive files with no new hits. Default stays exhaustive because multi-salt cases exist (WA reinstall, salt rotation) and dropping later candidates loses yield.
- `create_unified_indexes` wraps all 18 `CREATE INDEX` in one `BEGIN/COMMIT`; temporarily bumps `PRAGMA cache_size=-262144` (256 MiB) during index build only, restores caller's 128 MiB after. Cache-locality win, not fsync (fsync was already gone via `journal_mode=MEMORY`).
- `--profile` CLI flag: dumps per-stage `time.perf_counter` timings to `unify_profile.json` alongside output DB. Stage records: `extract_indexeddb`, `load_decrypted_sqlite`, `build_lid_resolver`, `build_unified_db`, `media_index`.
- `--media-only <path-to-unified.db>` CLI flag: run only media indexing against an existing unified DB. Enables deferring the O(files*size) SHA-256 pass off the target machine.
- Cross-OS unify guard verified: no `winreg`, `win32*`, `ctypes.WinDLL` at import time; `--unify` code path is Linux/macOS-clean.

**Code changes (waren6.ps1):**

- New `Get-SqliteRecordSizeForType` helper: table lookup for SQLite serial-type varint byte sizes.
- New `Find-SqliteBlobCandidates`: schema-agnostic scanner accepting header sizes 3-8 (2-7 column tables) and enumerating any column whose type varint encodes a 32 or 48 byte BLOB.
- New `Find-SessionClientKeyCandidates`: combines legacy `Get-WalSettingsData` fast path with the broad scanner across both WAL and main .db.
- New `Test-ClientKeyAgainstSessionsDir`: SHA-1 candidate blob and check for existing `sessions/<40-hex>/` directory. Schema-agnostic validation.
- New `Find-SqliteSettingsRecords` + `Get-SettingsRecords`: same tier-cascade for `nativeSettings.dec.db-wal` -> `nativeSettings.dec.db` so DB-key discovery survives the same schema shift.
- Rewrote client-key recovery block: two-tier flow (Tier 1 legacy, Tier 2 broad+SHA-1-match). Full diagnostic dump on total failure (file sizes, sessions dir names, candidate previews) so next debugging round has data.
- ASCII-only strings throughout the new code (PS 5.1 default codepage doesn't handle em-dash / right-arrow -- caused parse errors on first attempt).

**Deferred (need real numbers from `--profile` first):**

- Store 8 parse + genericStorage fuzzy merge `ProcessPoolExecutor`. Adversarial review flagged the estimate as oversold on target (Windows spawn cost + pickle) and requires ordering-determinism guard to preserve reproducibility.
- LevelDB pipeline read + parallel V8/Blink deserialize. Depends on `cryptography` actually releasing the GIL (OpenSSL-backed: yes; PyCryptodome fallback: no); requires runtime backend detection.
- Commit consolidation 29 -> 3. Adversarial review corrected the estimate from 3-5s down to 300-800ms because `journal_mode=MEMORY + synchronous=OFF` are already set. Small ROI, real regression risk if `isolation_level` misconfigured. Revisit only if `--profile` shows this dominates.

**Docs updates:**

- `LLM.txt`: appended Performance Reality, Split-Machine Workflow, Flags Added, What NOT to Do, Cross-OS Unify, and Session Key Recovery sections. Also updated pointers at the tail.
- `docs/kb/perf/Bottlenecks.md`: replaced with real research-backed ranking, cross-cutting invariants, and deferred items.
- `docs/kb/adr/ADR-003-split-machine-workflow.md`: new.
- `docs/kb/adr/ADR-004-session-key-schema-agnostic.md`: new.

## 2026-09-04 — Compiled page crypto & pipeline optimizations (ADR-008)

Implemented the hybrid zero-disk-binary optimization sprint combining in-memory C# via `Add-Type` and Python algorithmic optimizations. All 111 unit tests pass (`Ran 111 tests in 14.349s: OK`).

**Measured Microbenchmarks:**
- **In-Memory C# SQLite Page Decryption:** 20.76x faster than interpreted PowerShell (129.3 ms vs 2684.7 ms on 2,500 pages / 10.24 MB; throughput boosted from 3.6 MB/s to 75.5 MB/s). Verified 100% byte-for-byte exactness (0 diffs). Preserves zero `.exe` disk footprint, preventing Defender SmartScreen blocks and EDR alarms.
- **Store 8 Opaque Key Pinning:** 5.95x faster decryption across multi-candidate key suites (17.79 ms vs 105.82 ms per 2,000 messages) by attempting the winning `(ikm, salt, info)` candidate first and eliminating thousands of redundant decryptor setups and PKCS7 padding exceptions.
- **`parse_msg_key` LRU Caching:** 5.02x faster lookup throughput across message joins and table cross-referencing (4.60 ms vs 23.07 ms for 50k calls).
- **`pick_generic_text` Fuzzy Short-Circuit:** 4.00x faster execution (25.38 ms vs 101.64 ms for 10k matches) using the strict tuple score invariant `(0, ...) < (1, ...)`.
- **Early Varint Filter:** Rejects 99.9% of candidate offsets in `Find-SqliteBlobCandidates` before allocating `ArrayList` objects.
- **PowerShell De-AI & Deduplication:** Removed 167 lines of redundant inner functions inside `Start-WAren6` by promoting `Install-WAren6PythonSilently` and `Get-WAren6EmbeddedPython` to top-level helpers; streamlined robocopy fallback to `/ZB`.

## 2026-09-04 — Zero-dependency architecture & live field benchmark (ADR-009)

Completed full transition to a zero-pip, 100% self-contained toolkit with enhanced operator ease-of-use. Verified on live WhatsApp Desktop instance (`2.2634.101.0`). All 111 unit tests pass (`Ran 111 tests in 12.787s: OK`).

**Key Architectural Advancements:**
- **Zero Pip Dependencies:** Vendored `ccl_chromium_reader` and `ccl_simplesnappy` (<850 KB total) into `vendor/`. Prepend `vendor/` in `waren6.py` and wrapped optional brotli import. Zero pip packages required to run unification.
- **Native Windows AES-128-CBC (`bcrypt.dll`):** Implemented direct Windows CNG bindings via Python `ctypes`, providing hardware-accelerated AES-NI decryption without requiring the 20+ MB `cryptography` wheel.
- **Native .NET ZipFile Compression:** Replaced slow/limited `Compress-Archive` with `[System.IO.Compression.ZipFile]::CreateFromDirectory` (built into .NET 4.5+ across all Windows).
- **Interactive Operator Launcher:** Added interactive console banner when `waren6.ps1` runs without arguments, allowing operators to run extraction with safe defaults by pressing `Enter`.
- **Adaptive Robocopy Elevation Check:** Evaluates user token elevation before applying `/ZB`, preventing error 1314 / exit code 16 on standard user accounts.
- **Housekeeping:** Purged past case run artifacts (~68 MB of `WAren6_20260714181552*`) and moved loose root audit documentation to `docs/perf/`.

**Live Benchmark Results (Live WhatsApp Desktop on Host Machine):**
- **Total Extraction Time:** 142.7 seconds.
- **Step [1/4] Acquisition & Locked Copy:** 34.6s (LocalState copy in 1.4s; WebView2 runtime probe timeout safely capped at 20s).
- **Step [2/4] Decryption Engine:** 3.0s (In-memory C# `WAren6CryptoEngine` decrypted 14 SQLite DB/WAL files; Tier 2 broad scanner recovered client key matching session `757B3332907CC72EA1D1B9D90F2426F187B8BFE1`).
- **Step [3/4] Unified DB Extractor:** 102.4s total:
  - Vendored LevelDB extraction: 89.1s (extracted 14,377 messages, 16,253 message-infos, 2,749 reactions across 47 stores).
  - SQLite message & contact loading: 0.2s (loaded 23,938 rows).
  - Unified DB creation & indexing: 11.7s (indexed 27,166 messages, 1,550 contacts across 105 chats into self-contained 22.6 MB `unified_whatsapp.db`).
- **Step [4/4] Forensic Manifest & Reports:** 2.6s.
- **Extraction Yield:** 27,166 messages (13,602 sent, 8,352 received), 1,550 contacts (774 with phone), 105 chats, 2,749 reactions. 0 duplicate message key groups. Status: OK.

## 2026-09-04 — Field Kit v2.0.0 Milestone & Log Issue Fixes

- **Field Kit v2.0.0 Released**: Bumped Field Kit to 2.0.0 across metadata (`version.json`, `fieldkit-version.json`), PowerShell engine (`$global:WAren6Version`), documentation (`README.md`, `LLM.txt`), and test suites. Reader remains on independent `1.7.0` release track.
- **`System.SByte` Overflow Fix**: In `waren6.ps1` lines 3937 and 4272, replaced checked `[sbyte]` casts with two's-complement arithmetic (`if ($rawByte -ge 128) { $rawByte - 256 } else { $rawByte }`), resolving terminating exceptions on byte values $\ge 128$.
- **Chromium V8 Sparse Array Deserialization Fix**: In `ccl_v8_value_deserializer.py`, guarded sparse and dense array property loops with bounds-checking and list expansion, preventing `IndexError: list index out of range`.
- **Resilient Message Iteration**: Added `bad_deserializer_data_handler` to `idb.iterate_records()` in `waren6.py`, isolating bad records and allowing LevelDB extraction to continue across all messages.
- **Runtime Capture Cleanup**: Ensured `$runtimeCaptureRoot` is cleaned up unconditionally after staging, preventing leftover folders on timeout.

## Backlog

- Ask LO to run the fixed `waren6.ps1` on `ANIRBANDEYPC` and confirm the Tier 2 SHA-1-match path finds the client key. If it still fails, the diagnostic dump will tell us what shape WA moved to.
- Add a small microbench harness in `tests/perf/` for regression flags (not for correctness).
- Manual verification pass on very latest WhatsApp Desktop build (post 2.3010).



