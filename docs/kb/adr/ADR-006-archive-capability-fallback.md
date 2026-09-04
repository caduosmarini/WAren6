---
title: "ADR-006: Archive capability fallback"
tags: [adr, archive, field-kit]
status: Accepted
date: 2026-07-28
---

# ADR-006: Archive capability fallback

## Context

On `ANIRBANDEYPC` (Windows 11 Build 22000), acquisition and decryption completed but archive creation failed. The bundled BSD tar accepted `--zstd` but could not launch the external `zstd.exe` program. The previous version-only capability check reported a false positive.

## Decision

Determine tar+zstd availability using a small temporary archive create-and-readback probe. If it fails, create and verify a ZIP archive. Do not require installing zstd on evidence targets.

Add `--no-archive` for a normal live acquisition/unification run that retains the case folder. It deliberately rejects Telegram transfer, encryption, and auto-delete because those operations require a verified archive.

## Consequences

- Field targets without zstd complete with a verified ZIP archive.
- Telegram transfer works unchanged with either archive format through its existing CLI flags and split/verification flow.
- `--no-archive` supports live integrity validation without creating an archive, but operators must archive later before transfer.

## Alternatives considered

1. Require `zstd.exe` on every target: rejected because it creates deployment friction.
2. Always use ZIP: rejected because functional tar+zstd remains a useful preferred format.
3. Trust tar version output: rejected because the live failure disproved it.
