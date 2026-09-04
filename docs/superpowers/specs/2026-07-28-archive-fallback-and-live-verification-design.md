---
title: "Archive fallback and live verification"
status: approved-design
date: 2026-07-28
---

# Archive fallback and live verification

## Context

The Windows 11 target uses BSD tar. Its `--zstd` option delegates compression to an external `zstd.exe`, which is not installed. The prior availability check accepted `tar --zstd --version`, but that command does not prove that archive creation will work. The live acquisition therefore completed its forensic extraction and failed only during `.tar.zst` creation.

## Decision

1. Detect usable tar+zstd support with a short-lived, real archive round-trip. If the probe fails, create and verify a ZIP archive instead.
2. Add `--no-archive` for a normal hybrid acquisition and unification run that retains the case folder without compression, hashing, or Telegram transfer.
3. Reject `--no-archive` combined with Telegram transfer or auto-delete, because Telegram operates on a verified archive.
4. Keep Telegram credential handling CLI-only. Existing `-tg <token> -cid <chat-id>` behavior remains: verified archive, sub-50 MiB splitting, per-part upload-size verification, and a recombination manifest.
5. Keep the failed target case until a new live hybrid run with `--no-archive` produces a valid unified database and source-vs-unified validation report. Delete only that failed case after the successful verification.

## Verification

- Automated coverage proves the tar probe uses real archive creation and that archive creation falls back to ZIP when the probe is unavailable.
- Automated coverage proves `--no-archive` skips archive and Telegram work, and rejects incompatible transfer flags.
- The full Python test suite and PowerShell 5.1 parser check pass.
- On `ANIRBANDEYPC`, a live hybrid run with `--no-archive` finishes acquisition, decryption, unification, and validation. The resulting `unified_whatsapp.db` is queried for source and unified message counts, then integrity checks are reviewed.

## Non-goals

- Installing zstd on the target.
- Changing the Telegram API, credential storage, encryption, part size, or upload protocol.
- Replacing the current archive formats beyond the required verified ZIP fallback.
