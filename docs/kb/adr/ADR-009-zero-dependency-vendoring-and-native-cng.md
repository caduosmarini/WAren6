---
title: ADR-009 Zero-Dependency Vendoring, Native Windows CNG, and Operator Usability
tags: [adr, zero-dependency, vendor, bcrypt, usability, powershell]
date: 2026-09-04
---

# ADR-009: Zero-Dependency Vendoring, Native Windows CNG, and Operator Usability

## Context

In digital forensics and incident response (DFIR), operational environments are frequently constrained:
1. **Air-gapped Targets**: Forensic analysis laptops and seized evidence machines often have no internet access.
2. **Missing Developer Tooling**: Enterprise Windows systems rarely have `git.exe` installed. Prior requirements to run `pip install git+https://github.com/cclgroupltd/ccl_chromium_reader.git` resulted in fatal errors.
3. **Heavy C/Rust Extensions**: Requiring `pip install cryptography` added 20+ MB of external wheels, requiring matching Python ABIs or C/Rust build tools.
4. **Compression Roadblocks**: Windows 10/11 BSD `tar.exe` lacks bundled `zstd.exe`, while `Compress-Archive` suffers from a 2 GB file-size limit and high CPU overhead.
5. **Privilege Edge Cases**: Robocopy called with `/ZB` (backup mode) fails with Error 1314 / Exit Code 16 when running under a standard (non-elevated) user token lacking `SeBackupPrivilege`.

## Decision

We eliminated all external pip dependencies and streamlined operator usability across the toolkit:

1. **Vendored Pure-Python Chromium Reader (`vendor/`):**
   - Vendored `ccl_chromium_reader` and `ccl_simplesnappy` (<850 KB total) into `vendor/`.
   - Modified `waren6.py` to prepend `vendor/` to `sys.path` dynamically.
   - Made the unused, HTTP-cache-only `brotli` import optional in the vendored reader.
   - Requirement to run `pip install git+...` is completely removed.

2. **Native Windows Cryptography Next Generation (`bcrypt.dll` via `ctypes`):**
   - Implemented direct Windows CNG bindings in `_bcrypt_aes_cbc_decrypt()` using Python standard library `ctypes`.
   - Utilizes Windows' built-in `bcrypt.dll` (present on all Windows versions since Vista) for hardware-accelerated AES-128-CBC with AES-NI instructions.
   - Retained stdlib `hmac` + `hashlib` for RFC 5869 HKDF-SHA256.
   - Requirement to install the `cryptography` wheel is completely removed.

3. **High-Performance Native .NET Zip Compression:**
   - Replaced `Compress-Archive` fallback in `waren6.ps1` with .NET `[System.IO.Compression.ZipFile]::CreateFromDirectory`.
   - Eliminates the 2 GB archive ceiling, avoids external `zstd.exe` failures, and compresses 3–5x faster.

4. **Non-Technical Interactive Launcher:**
   - Added an interactive console banner when `waren6.ps1` is executed without arguments: detects WhatsApp presence, explains defaults, and allows operators to launch full extraction simply by pressing `Enter`.

5. **Adaptive Robocopy Privilege Detection:**
   - Evaluates user elevation (`[Security.Principal.WindowsPrincipal]::IsInRole`) before applying `/ZB`. Uses standard multithreaded `/MT:8 /R:1 /W:1` for standard users, preventing Exit Code 16.

## Consequences

- **Required pip packages:** **0** (Standard Python 3.10+ stdlib only).
- **External tools needed:** **0** (No `git`, no `zstd`, no C/Rust compilers).
- **PowerShell compatibility:** 100% verified on native **Windows PowerShell 5.1** (no PowerShell 7 needed).
- **Air-gap readiness:** 100% self-contained out of the box.
- **Live Verification:** Extracted **27,166 messages** and **1,550 contacts** across 105 chats from a live WhatsApp Desktop instance with 0 pip packages installed in 142.7s.

## References

- [[perf/Bottlenecks]]
- [[ADR-002-store8-hybrid-recovery]]
- [[ADR-008-compiled-page-crypto-and-pipeline-optimizations]]
