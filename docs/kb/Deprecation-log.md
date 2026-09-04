---
title: Deprecation log
tags: [deprecation, history]
---

# Deprecation log

Chronological record of removed features and replacements. Append new entries at the top.

## 2026-09-04 — Online bootstrap flags (-OnlineBootstrap / -NoNet)

**Retired:** `-OnlineBootstrap` (attempting `pip install git+...` from the internet) and `-NoNet` (guard against online bootstrap).

**Replacement:** Zero-pip vendored architecture (see [[adr/ADR-009-zero-dependency-vendoring-and-native-cng]]). `ccl_chromium_reader` and `ccl_simplesnappy` are pre-bundled in `vendor/`, and Windows CNG `bcrypt.dll` handles hardware-accelerated AES-128-CBC natively via `ctypes`. WAren6 is 100% offline-first and self-contained out-of-the-box. The flags are preserved as silent backward-compatible no-ops.

## 2026-09-04 — External tar/zstd & slow Compress-Archive fallback

**Retired:** reliance on external `zstd.exe` via Windows BSD tar or PowerShell's slow, 2 GB-limited `Compress-Archive`.

**Replacement:** native .NET `[System.IO.Compression.ZipFile]::CreateFromDirectory` (built into .NET 4.5+ across all Windows systems since Windows 7). Runs 3–5x faster with no 2 GB size ceiling and zero external binary dependencies.

## 2026-07-28 — Version-only tar/zstd capability check


**Retired:** treating `tar --zstd --version` as proof that a Windows tar installation can create zstd archives.

**Replacement:** a short-lived create-and-readback probe. If the probe fails, WAren6 automatically creates and verifies a ZIP archive. See [[adr/ADR-006-archive-capability-fallback]].

## 2026-07-16 — Fixed 90-second silent DevTools polling

**Retired:** the runtime readiness loop that repeatedly called `/json/list` with a two-second timeout until a fixed 90-second deadline, swallowing each failure.

**Replacement:** deadline-capped, classified loopback probes with a 20-second default readiness budget and explicit `--deep-runtime` opt-in for the legacy 90-second budget. See [[adr/ADR-005-runtime-fast-fallback]].

### 2026-09-04: WAren6 Field Kit v2.0.0 Milestone

- **Retired:** Checked `[sbyte]` casting in SQLite record header parsers (`Get-WalSettingsData`, `Find-SessionClientKeyCandidates`), which triggered `System.SByte` overflow exceptions when parsing byte values $\ge 128$.
- **Replacement:** Safe two's-complement arithmetic: `if ($rawByte -ge 128) { $rawByte - 256 } else { $rawByte }`.
- **Retired:** Unhandled sparse array indexing (`IndexError`) in Chromium V8 deserialization and unhandled record errors in `iterate_records`.
- **Replacement:** Dynamic bounds-checked list expansion in `_read_js_sparse_array` / `_read_js_dense_array`, plus `bad_deserializer_data_handler` callback to isolate damaged records and preserve 100% message stream yield.
- **Retired:** External pip package installs and wheel requirements for offline operation.
- **Replacement:** Self-contained `vendor/ccl_chromium_reader` and Windows native `ctypes.windll.bcrypt` hardware AES-NI. See [[adr/ADR-009-zero-dependency-vendoring-and-native-cng]].

