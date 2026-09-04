---
title: ADR-008 Compiled Page Crypto and Pipeline Optimizations
tags: [adr, crypto, perf, powershell, python]
date: 2026-09-04
---

# ADR-008: Compiled Page Crypto and Pipeline Optimizations

## Context

WAren6 must operate rapidly and reliably on modest field-kit hardware (older dual-core laptops, low-power evidence workstations, slow SATA or mechanical disks, 4-8 GB RAM).

Profiling identified key bottlenecks in the acquisition, decryption, and unification phases:
1. **PowerShell Database Decryption:** SQLite page decryption (`Unprotect-DatabaseFile` and `Unprotect-DatabaseWalFile`) in pure interpreted PowerShell processed ~3.6 MB/s due to per-page function call invocation, object boxing, and array slice copying across thousands of 4096-byte pages.
2. **AV / SmartScreen Constraint:** Producing a standalone native `.exe` binary triggers Windows SmartScreen warnings, antivirus false positives, and strict EDR blocks on forensic acquisition targets, threatening non-technical operator friction and chain-of-custody rejection.
3. **Store 8 Opaque Key Combinations:** During Store 8 opaque decryption, candidate keys, salts, and info strings produce multiple trial combinations per message. On multi-thousand message sets, unpinned trial search repeatedly initializes decryptors and raises thousands of PKCS7 padding exceptions.
4. **Key Parsing & Fuzzy Selection:** `parse_msg_key` was called tens of thousands of times across joins without memoization; `pick_generic_text` repeatedly performed Unicode normalization and regex whitespace stripping across candidate lists even after exact timestamp matches (`delta == 0`) were discovered.

## Decision

We implemented a hybrid, zero-disk-binary optimization strategy across both PowerShell and Python layers:

1. **In-Memory Compiled C# Crypto Engine (`Initialize-WAren6CryptoEngine`):**
   - Compiles an in-memory class `WAren6CryptoEngine` via `Add-Type -TypeDefinition ... -ReferencedAssemblies $bcPath`.
   - Directly binds to the existing, trusted `BouncyCastle.Cryptography.dll` assembly.
   - Performs block-copy buffer operations, IV generation, and native OFB AES page decryption inside a compiled loop.
   - Restores reserved SQLite bytes `0x10-0x17` with byte-for-byte exactness.
   - Retains a transparent, fully functional fallback to the interpreted PowerShell loop if C# compilation is unavailable.
   - Zero `.exe` files written to disk; executes entirely within the existing `powershell.exe` CLR host.

2. **Early Varint Rejection in Schema-Agnostic Scanner (`Find-SqliteBlobCandidates`):**
   - Inserted `$hasWantedVarint` check scanning header type varints before allocating `ArrayList` instances or parsing row structures, eliminating 99.9% of dead offsets.

3. **Store 8 Winning Candidate Pinning (`pinned_candidate`):**
   - Added `pinned_candidate` tracking to `Store8CryptoContext` and `decrypt_store8_opaque_record`.
   - When a candidate `(ikm, salt, info)` successfully decrypts a record, it is pinned and attempted first on all subsequent messages.
   - Completely eliminates redundant trial decryptor initializations and thousands of PKCS7 exception overheads.

4. **Logical Key Caching & Fuzzy Selection Short-Circuiting:**
   - Decorated `parse_msg_key` with `@functools.lru_cache(maxsize=32768)`.
   - Short-circuited `pick_generic_text` when `delta == 0 and best is not None`, leveraging the strict tuple score invariant `(0, ...) < (1, ...)`.

## Consequences

- **SQLite Decryption:** Achieved **20.76x faster** execution (129.3 ms vs 2684.7 ms on 2,500 pages / 10.24 MB; throughput boosted from 3.6 MB/s to 75.5 MB/s) with 100% byte-for-byte exact match verified.
- **Store 8 Opaque Decryption:** Achieved **5.95x faster** decryption across candidate key suites (17.79 ms vs 105.82 ms per 2,000 messages) with identical yield.
- **Key Parsing:** 5.02x faster lookup throughput across message joins.
- **Fuzzy Text Matching:** 4.00x faster execution on message candidate batches.
- **Zero Antivirus Friction:** Zero standalone `.exe` binaries created; completely avoids Defender SmartScreen warnings and maintains forensic integrity.
- **Full Test Suite:** 111/111 unit tests passing (`Ran 111 tests in 14.349s: OK`).

## Alternatives Considered

- *Compiling a standalone C/C++ or Go `.exe` helper:* Rejected due to high risk of Windows Defender / SmartScreen blocking on field machines and deployment complexity.
- *Multiprocessing spawn pool in Python for Store 8:* Rejected on low-power dual-core systems due to Windows process creation overhead, IPC pickle latency, and non-deterministic row ordering risk.

## References

- [[perf/Bottlenecks]]
- [[ADR-004-session-key-schema-agnostic]]
- [[ADR-007-logical-message-key-relations]]
