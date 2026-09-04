---
title: "ADR-007: Logical message-key relations"
tags: [adr, schema, integrity]
status: Accepted
date: 2026-07-28
---

# ADR-007: Logical message-key relations

## Context

WAren6 intentionally preserves source variants that share a `messages.msg_key`. The initial schema nevertheless declared foreign keys from media, receipt, reaction, mention, and edit tables to `messages(msg_key)`. SQLite requires a foreign-key parent to be unique, so `PRAGMA foreign_key_check` failed with a schema mismatch on a live database.

## Decision

Treat `msg_key` as an indexed logical correlation key, not a SQLite foreign key. Keep valid foreign keys that target actual primary keys, such as chat and group identifiers.

## Consequences

- Variant evidence remains preservable without schema-level rejection.
- `integrity_check`, `quick_check`, and `foreign_key_check` can all complete on newly built databases.
- Consumers join child evidence to messages by `msg_key` with explicit query semantics when variants require disambiguation.

## Alternatives considered

1. Make `msg_key` unique: rejected because it drops or conflates valid source variants.
2. Add a synthetic message row ID to every child table: deferred; it would require an arbitrary variant-selection policy and is not necessary for the existing evidence queries.
