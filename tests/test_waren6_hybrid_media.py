import contextlib
import io
import re
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import waren6


class UnifiedSchemaPerformanceTests(unittest.TestCase):
    def test_quote_enrichment_uses_reply_index_and_preserves_quote_semantics(self):
        source = Path(waren6.__file__).read_text(encoding="utf-8")
        quote_start = source.index("# ── Enrich quoted-message bodies")
        quote_source = source[quote_start:source.index("# ── Deduplicate only stable IndexedDB key duplicates", quote_start)]
        sql = re.search(r'cursor.execute\("""(.*?)"""\)', quote_source, re.S).group(1)
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(waren6.UNIFIED_TABLE_SCHEMA)
            conn.executemany(
                """INSERT INTO messages(msg_id, chat_jid, timestamp, text, msg_type,
                   quoted_stanza_id, quoted_msg_body, quoted_msg_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    ("original", "a@c.us", 20, "later", "video", None, None, None),
                    ("original", "a@c.us", 10, "earliest", "chat", None, None, None),
                    ("original", "a@c.us", 10, "same-time later row", "image", None, None, None),
                    ("original", "b@c.us", 1, "other chat", "audio", None, None, None),
                    ("reply", "a@c.us", 30, "reply", "chat", "original", None, None),
                    ("blank-preview", "a@c.us", 31, "reply", "chat", "original", "  ", "image"),
                    ("captured-preview", "a@c.us", 32, "reply", "chat", "original", "captured snapshot", "video"),
                    ("other-reply", "b@c.us", 33, "reply", "chat", "original", None, None),
                    ("missing", "a@c.us", 34, "reply", "chat", "absent", None, None),
                ],
            )
            waren6.create_unified_indexes(conn)
            plan = "\n".join(str(row) for row in conn.execute("EXPLAIN QUERY PLAN " + sql))
            self.assertIn("idx_messages_chat_quote", plan)
            conn.execute(sql)
            previews = dict(
                (row[0], row[1:]) for row in conn.execute(
                    "SELECT msg_id, quoted_msg_body, quoted_msg_type FROM messages WHERE quoted_stanza_id IS NOT NULL"
                )
            )
            self.assertEqual(previews["reply"], ("earliest", "chat"))
            self.assertEqual(previews["blank-preview"], ("earliest", "image"))
            self.assertEqual(previews["captured-preview"], ("captured snapshot", "video"))
            self.assertEqual(previews["other-reply"], ("other chat", "audio"))
            self.assertEqual(previews["missing"], (None, None))
            # Reapplying index creation is safe for an existing generated case.
            waren6.create_unified_indexes(conn)
        finally:
            conn.close()

    def test_schema_foreign_key_check_allows_intentional_duplicate_message_keys(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(waren6.UNIFIED_SCHEMA)
            conn.execute("INSERT INTO chats(chat_jid) VALUES (?)", ("0@c.us",))
            conn.executemany(
                """
                INSERT INTO messages(
                    msg_key, msg_id, chat_jid, timestamp, source, source_id, body_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("shared-logical-key", "first", "0@c.us", 1, "indexeddb", "first", "text_present"),
                    ("shared-logical-key", "second", "0@c.us", 2, "genericStorage", "second", "text_present"),
                ],
            )
            self.assertEqual(list(conn.execute("PRAGMA foreign_key_check")), [])
        finally:
            conn.close()

    def test_schema_indexes_quote_lookup_by_chat_and_message_id(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(waren6.UNIFIED_SCHEMA)
            indexes = {
                row[1]
                for row in conn.execute("PRAGMA index_list(messages)").fetchall()
            }
            self.assertIn("idx_messages_chat_msgid_ts", indexes)

            conn.execute(
                """
                INSERT INTO messages(
                    msg_key, msg_id, chat_jid, timestamp, text,
                    source, source_id, body_status
                )
                VALUES ('false_0@c.us_ORIGINAL', 'ORIGINAL', '0@c.us', 1770000000,
                        'quoted text', 'indexeddb', 'ORIGINAL', 'text_present')
                """
            )
            plan = "\n".join(
                str(row)
                for row in conn.execute(
                    """
                    EXPLAIN QUERY PLAN
                    SELECT o.text
                    FROM messages AS o
                    WHERE o.chat_jid = ?
                      AND o.msg_id = ?
                      AND o.text IS NOT NULL
                      AND TRIM(o.text) != ''
                    ORDER BY o.timestamp ASC, o.rowid ASC
                    LIMIT 1
                    """,
                    ("0@c.us", "ORIGINAL"),
                ).fetchall()
            )

            self.assertIn("idx_messages_chat_msgid_ts", plan)
        finally:
            conn.close()

    def test_schema_indexes_runtime_validation_by_message_key(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(waren6.UNIFIED_SCHEMA)
            indexes = {
                row[1]
                for row in conn.execute("PRAGMA index_list(messages)").fetchall()
            }
            self.assertIn("idx_messages_msg_key", indexes)

            plan = "\n".join(
                str(row)
                for row in conn.execute(
                    """
                    EXPLAIN QUERY PLAN
                    SELECT text, store8_decrypted_text
                    FROM messages
                    WHERE msg_key = ?
                    LIMIT 1
                    """,
                    ("false_0@c.us_STANZA",),
                ).fetchall()
            )

            self.assertIn("idx_messages_msg_key", plan)
        finally:
            conn.close()

    def test_schema_indexes_chat_timestamp_pagination(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(waren6.UNIFIED_SCHEMA)
            indexes = {
                row[1]
                for row in conn.execute("PRAGMA index_list(messages)").fetchall()
            }
            self.assertIn("idx_messages_chat_ts", indexes)

            plan = "\n".join(
                str(row)
                for row in conn.execute(
                    """
                    EXPLAIN QUERY PLAN
                    SELECT rowid
                    FROM messages
                    WHERE chat_jid = ?
                      AND (timestamp < ? OR (timestamp = ? AND rowid < ?))
                    ORDER BY timestamp DESC, rowid DESC
                    LIMIT 50
                    """,
                    ("12345@c.us", 1770000000, 1770000000, 99),
                ).fetchall()
            )

            self.assertIn("idx_messages_chat_ts", plan)
        finally:
            conn.close()

    def test_unified_builder_defers_indexes_until_after_message_bulk_load(self):
        source = Path(waren6.__file__).read_text(encoding="utf-8")
        build_start = source.index("def build_unified_db")
        build_end = source.index("def iter_local_media_files", build_start)
        build_source = source[build_start:build_end]

        self.assertIn("UNIFIED_TABLE_SCHEMA", source)
        self.assertIn("UNIFIED_INDEX_SCHEMA", source)
        self.assertIn("def create_unified_indexes", source)
        self.assertIn("cursor.executescript(UNIFIED_TABLE_SCHEMA)", build_source)
        self.assertIn("create_unified_indexes(conn)", build_source)
        self.assertNotIn("cursor.executescript(UNIFIED_SCHEMA)", build_source)
        self.assertLess(
            build_source.index("cursor.executescript(UNIFIED_TABLE_SCHEMA)"),
            build_source.index("execute_many_counting(cursor, message_insert_sql, idb_batch"),
        )
        self.assertLess(
            build_source.index("execute_many_counting(cursor, message_insert_sql, idb_batch"),
            build_source.index("create_unified_indexes(conn)"),
        )

    def test_unified_builder_uses_bulk_load_pragmas_for_generated_db(self):
        source = Path(waren6.__file__).read_text(encoding="utf-8")

        self.assertIn("def configure_unified_output_connection", source)
        self.assertIn("PRAGMA journal_mode=MEMORY", source)
        self.assertIn("PRAGMA synchronous=OFF", source)
        self.assertIn("PRAGMA temp_store=MEMORY", source)
        self.assertIn("PRAGMA mmap_size=268435456", source)
        self.assertIn("configure_unified_output_connection(conn)", source)

    def test_unifier_caches_repeated_jid_and_chat_id_parsing(self):
        source = Path(waren6.__file__).read_text(encoding="utf-8")
        build_start = source.index("def build_unified_db")
        build_end = source.index("def iter_local_media_files", build_start)
        build_source = source[build_start:build_end]

        self.assertIn("import functools", source)
        self.assertIn("@functools.lru_cache(maxsize=16384)", source)
        self.assertIn("def _normalize_chat_id_cached", source)
        self.assertIn("def cached_resolve_jid", build_source)
        raw_resolve_calls = re.findall(r"(?<!cached_)resolve_jid\(", build_source)
        self.assertEqual(len(raw_resolve_calls), 1)
        self.assertIn("cached_resolve_jid(", build_source)

    def test_unifier_batches_receipts_and_reactions(self):
        source = Path(waren6.__file__).read_text(encoding="utf-8")
        receipt_start = source.index("# ── Message receipts")
        reaction_start = source.index("# ── Reactions", receipt_start)
        final_start = source.index("# ── Final stats", reaction_start)
        receipt_source = source[receipt_start:reaction_start]
        reaction_source = source[reaction_start:final_start]

        self.assertIn("receipt_batch", receipt_source)
        self.assertIn("execute_many_counting(cursor", receipt_source)
        self.assertNotIn("cursor.execute(\"\"\"", receipt_source)
        self.assertIn("reaction_batch", reaction_source)
        self.assertIn("execute_many_counting(cursor", reaction_source)
        self.assertNotIn("cursor.execute(\"\"\"", reaction_source)

    def test_unifier_uses_set_based_quote_and_dedup_sql(self):
        source = Path(waren6.__file__).read_text(encoding="utf-8")
        quote_start = source.index("# ── Enrich quoted-message bodies")
        dedup_start = source.index("# ── Deduplicate only stable IndexedDB key duplicates", quote_start)
        summary_start = source.index("# Summary", dedup_start)
        quote_source = source[quote_start:dedup_start]
        dedup_source = source[dedup_start:summary_start]

        self.assertIn("ROW_NUMBER() OVER", quote_source)
        self.assertIn("FROM original_quotes", quote_source)
        self.assertNotIn("SELECT o.text", quote_source)
        self.assertIn("HAVING COUNT(*) > 1", dedup_source)
        self.assertNotIn("rowid NOT IN", dedup_source)

    def test_media_iterator_targets_transfer_and_blob_dirs_directly(self):
        source = Path(waren6.__file__).read_text(encoding="utf-8")
        iterator_start = source.index("def iter_local_media_files")
        iterator_end = source.index("def _case_relative", iterator_start)
        iterator_source = source[iterator_start:iterator_end]

        self.assertIn('sessions_root.glob("*/transfers")', iterator_source)
        self.assertIn('indexeddb_root.glob("*.indexeddb.blob")', iterator_source)
        self.assertNotIn('case_root / "sessions",', iterator_source)

    def test_wal_open_uses_caller_specific_sanity_tables(self):
        source = Path(waren6.__file__).read_text(encoding="utf-8")

        self.assertIn("def _apply_wal_and_open(db_path: pathlib.Path, sanity_table: str | None = None)", source)
        self.assertIn('_apply_wal_and_open(db_path, sanity_table="message")', source)
        self.assertIn('_apply_wal_and_open(db_path, sanity_table="UserStatuses")', source)
        self.assertNotIn('Native WAL read failed', source)


class BodyStatusTests(unittest.TestCase):
    def test_python_console_output_is_ascii_safe_for_powershell_capture(self):
        source = Path(waren6.__file__).read_text(encoding="utf-8")
        print_lines = [
            line for line in source.splitlines()
            if "print(" in line or "def print_progress" in line
        ]
        joined = "\n".join(print_lines)

        for bad in ("✓", "┌", "└", "│", "├", "»", "→", "█"):
            self.assertNotIn(bad, joined)
        self.assertIn("PROGRESS_ENABLED = not args.no_progress", source)
        self.assertIn("not sys.stdout.isatty()", source)
        self.assertIn('print("  Self phone: [redacted]")', source)
        self.assertNotIn('print(f"  Self phone: {self_phone}")', source)

    def test_lid_resolver_prints_one_compact_summary(self):
        contacts = [
            {"id": f"{idx}@lid", "phoneNumber": f"91000000000{idx}@c.us", "name": f"Example {idx}"}
            for idx in range(5)
        ]
        out = io.StringIO()

        with contextlib.redirect_stdout(out):
            lid_to_phone, _, _ = waren6.build_lid_resolver(contacts, [])

        self.assertEqual(len(lid_to_phone), 5)
        lines = [line for line in out.getvalue().splitlines() if line.strip()]
        self.assertEqual(lines, ["  LID mappings: 5 from IndexedDB contacts, 0 SQLite supplemental"])

    def test_default_unified_build_console_is_compact(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(out):
            db_path = Path(tmp) / "unified_whatsapp.db"
            waren6.build_unified_db(
                str(db_path),
                {"message": []},
                [],
                {},
                {},
                {},
                "indexeddb",
                "decrypted",
            )

        text = out.getvalue()
        self.assertIn("Source messages: 0 Store 8 rows, 0 genericStorage rows", text)
        self.assertNotIn("Inserting 0 messages", text)
        self.assertNotIn("Fallback enrichment", text)
        self.assertNotIn("Personal-chat fromMe fix", text)
        self.assertNotIn("fromMe coverage", text)

    def test_message_identity_uses_first_url_for_link_preview_duplicates(self):
        url = "https://youtube.com/shorts/4OarBibtuOk?si=xN2TX3HjX7hzzyY2"

        self.assertEqual(waren6.message_identity_text(url), url)
        self.assertEqual(
            waren6.message_identity_text(f"youtube.com {url} {url}"),
            url,
        )

    def test_classifies_expected_blank_rows_without_false_loss(self):
        self.assertEqual(
            waren6.classify_body_status(msg_type="image", media_filename="photo.jpg"),
            "media_only",
        )
        self.assertEqual(
            waren6.classify_body_status(msg_type="call_log"),
            "call_event",
        )
        self.assertEqual(
            waren6.classify_body_status(source_recovery="store8_opaque_unresolved", store8_status="opaque_unresolved"),
            "opaque_unresolved",
        )
        self.assertEqual(
            waren6.classify_body_status(msg_type="chat"),
            "missing_unexpected",
        )
        self.assertEqual(
            waren6.classify_body_status(msg_type="e2e_notification"),
            "system_event",
        )
        self.assertEqual(
            waren6.classify_body_status(msg_type="gp2"),
            "system_event",
        )

    def test_runtime_text_validation_checks_imported_live_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "unified_whatsapp.db"
            conn = sqlite3.connect(db_path)
            conn.executescript(waren6.UNIFIED_SCHEMA)
            conn.execute(
                """
                INSERT INTO messages(msg_key, chat_jid, timestamp, text, source, source_id, body_status)
                VALUES ('true_0@c.us_A', '0@c.us', 1, 'hello live', 'indexeddb', 'A', 'runtime_store8_decoded')
                """
            )
            conn.commit()
            conn.close()

            report = waren6.validate_unified_database(
                db_path,
                runtime_store8_supplement={
                    "records_by_msg_key": {
                        "true_0@c.us_A": {"msg_key": "true_0@c.us_A", "body": "hello live"}
                    }
                },
            )

        self.assertEqual(report["metrics"]["runtime_text_keys_missing_from_unified"], 0)
        self.assertEqual(report["status"], "ok")

    def test_exact_source_text_gaps_are_warnings_and_samples_are_hashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "unified_whatsapp.db"
            conn = sqlite3.connect(db_path)
            conn.executescript(waren6.UNIFIED_SCHEMA)
            conn.execute(
                """
                INSERT INTO messages(msg_key, chat_jid, timestamp, text, source, source_id, body_status)
                VALUES ('true_0@c.us_A', '0@c.us', 1, 'trimmed preview', 'indexeddb', 'A', 'text_present')
                """
            )
            conn.commit()
            conn.close()

            report = waren6.validate_unified_database(
                db_path,
                sqlite_messages=[
                    {"chatId": "0@c.us", "timestamp": 1, "text": "full preview text with private content"}
                ],
            )

        self.assertEqual(report["metrics"]["missing_exact_text_keys"], 1)
        self.assertIn("missing_exact_text_keys", report["warnings"])
        self.assertNotIn("missing_exact_text_keys", report["errors"])
        self.assertEqual(report["status"], "ok")
        self.assertIn("text_sha256", report["missing_exact_text_samples"][0])
        self.assertNotIn("text", report["missing_exact_text_samples"][0])

    def test_build_unified_db_inserts_runtime_only_text_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "unified_whatsapp.db"
            runtime_key = "true_12345@c.us_ABCDEF"
            runtime = {
                "summary": {"enabled": True, "path": "runtime.jsonl", "usable_records": 1},
                "records_by_msg_key": {
                    runtime_key: {
                        "msg_key": runtime_key,
                        "timestamp": 1770000000,
                        "type": "chat",
                        "from_me": True,
                        "chat_jid": "12345@c.us",
                        "body": "runtime-only text",
                    }
                },
            }

            waren6.build_unified_db(
                str(db_path),
                {"message": []},
                [],
                {},
                {},
                {},
                "indexeddb",
                "decrypted",
                runtime_store8_supplement=runtime,
            )

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                """
                SELECT text, source, source_recovery, body_status, store8_decryption_status
                FROM messages WHERE msg_key = ?
                """,
                (runtime_key,),
            ).fetchone()
            conn.close()

            report = waren6.validate_unified_database(db_path, runtime_store8_supplement=runtime)

        self.assertEqual(row, (
            "runtime-only text",
            "runtime_store8",
            "runtime_store8_only",
            "runtime_store8_decoded",
            "runtime_store8_decoded",
        ))
        self.assertEqual(report["metrics"]["runtime_text_keys_missing_from_unified"], 0)
        self.assertEqual(report["metrics"]["missing_unexpected"], 0)

    def test_runtime_only_rows_consume_matching_generic_storage_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "unified_whatsapp.db"
            runtime_key = "true_12345@c.us_ABCDEF"
            runtime = {
                "summary": {"enabled": True, "path": "runtime.jsonl", "usable_records": 1},
                "records_by_msg_key": {
                    runtime_key: {
                        "msg_key": runtime_key,
                        "timestamp": 1770000000,
                        "type": "chat",
                        "from_me": True,
                        "chat_jid": "12345@c.us",
                        "body": "same text from runtime and sqlite",
                    }
                },
            }

            waren6.build_unified_db(
                str(db_path),
                {"message": []},
                [
                    {
                        "id": 7,
                        "chatId": "12345@c.us",
                        "timestamp": 1770000000,
                        "text": "same text from runtime and sqlite",
                    }
                ],
                {},
                {},
                {},
                "indexeddb",
                "decrypted",
                runtime_store8_supplement=runtime,
            )

            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                """
                SELECT msg_key, source, source_recovery, text
                FROM messages
                WHERE chat_jid = '12345@c.us'
                ORDER BY rowid
                """
            ).fetchall()
            conn.close()

        self.assertEqual(rows, [
            (
                runtime_key,
                "runtime_store8",
                "runtime_store8_only",
                "same text from runtime and sqlite",
            )
        ])

    def test_runtime_only_revoked_rows_are_preserved_without_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "unified_whatsapp.db"
            runtime_key = "false_fixturegroup@g.us_DELETE_999@lid"
            runtime = {
                "summary": {"enabled": True, "path": "runtime.jsonl", "usable_records": 1},
                "records_by_msg_key": {
                    runtime_key: {
                        "msg_key": runtime_key,
                        "timestamp": 1770000000,
                        "type": "revoked",
                        "subtype": "sender",
                        "from_me": False,
                        "chat_jid": "fixturegroup@g.us",
                        "sender_jid": "999@lid",
                    }
                },
            }

            waren6.build_unified_db(
                str(db_path),
                {"message": []},
                [],
                {},
                {},
                {},
                "indexeddb",
                "decrypted",
                runtime_store8_supplement=runtime,
            )

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                """
                SELECT text, msg_type, from_me, sender_jid, source, source_recovery, body_status
                FROM messages WHERE msg_key = ?
                """,
                (runtime_key,),
            ).fetchone()
            conn.close()

        self.assertEqual(row, (
            None,
            "revoked",
            0,
            "999@lid",
            "runtime_store8",
            "runtime_store8_only",
            "revoked_or_deleted",
        ))

    def test_runtime_only_quote_context_is_preserved_and_enriched(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "unified_whatsapp.db"
            original_key = "false_fixturegroup@g.us_ORIG_111@lid"
            reply_key = "false_fixturegroup@g.us_REPLY_222@lid"
            runtime = {
                "summary": {"enabled": True, "path": "runtime.jsonl", "usable_records": 2},
                "records_by_msg_key": {
                    original_key: {
                        "msg_key": original_key,
                        "timestamp": 1770000000,
                        "type": "chat",
                        "from_me": False,
                        "chat_jid": "fixturegroup@g.us",
                        "sender_jid": "111@lid",
                        "body": "original body",
                    },
                    reply_key: {
                        "msg_key": reply_key,
                        "timestamp": 1770000010,
                        "type": "chat",
                        "from_me": False,
                        "chat_jid": "fixturegroup@g.us",
                        "sender_jid": "222@lid",
                        "body": "reply body",
                        "quoted_stanza_id": "ORIG",
                        "quoted_participant": "111@lid",
                        "quoted_msg_type": "chat",
                    },
                },
            }

            waren6.build_unified_db(
                str(db_path),
                {"message": []},
                [],
                {},
                {},
                {},
                "indexeddb",
                "decrypted",
                runtime_store8_supplement=runtime,
            )

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                """
                SELECT quoted_stanza_id, quoted_participant, quoted_msg_body, quoted_msg_type
                FROM messages WHERE msg_key = ?
                """,
                (reply_key,),
            ).fetchone()
            conn.close()

        self.assertEqual(row, ("ORIG", "111@lid", "original body", "chat"))

    def test_store8_edit_marker_sets_message_edit_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "unified_whatsapp.db"
            msg_key = "true_12345@c.us_MSG"

            waren6.build_unified_db(
                str(db_path),
                {
                    "message": [
                        {
                            "id": msg_key,
                            "t": 1770000000,
                            "type": "chat",
                            "body": "edited text",
                            "latestEditMsgKey": "true_12345@c.us_EDIT",
                            "latestEditSenderTimestampMs": 1770000065000,
                        }
                    ],
                },
                [],
                {},
                {},
                {},
                "indexeddb",
                "decrypted",
            )

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                """
                SELECT is_edited, edited_at, edit_count, edit_history_status
                FROM messages WHERE msg_key = ?
                """,
                (msg_key,),
            ).fetchone()
            metrics = waren6.validate_unified_database(db_path)["metrics"]
            conn.close()

        self.assertEqual(row, (1, 1770000065, 0, "marker_only"))
        self.assertEqual(metrics["edited_message_markers"], 1)

    def test_message_edit_protocol_is_recorded_and_target_marked(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "unified_whatsapp.db"
            target_key = "true_12345@c.us_TARGET"
            edit_key = "true_12345@c.us_EDIT"

            waren6.build_unified_db(
                str(db_path),
                {
                    "message": [
                        {
                            "id": target_key,
                            "t": 1770000000,
                            "type": "chat",
                            "body": "new text",
                            "latestEditMsgKey": edit_key,
                            "latestEditSenderTimestampMs": 1770000100000,
                        },
                        {
                            "id": edit_key,
                            "t": 1770000100,
                            "type": "protocol",
                            "subtype": "message_edit",
                            "body": "new text",
                            "protocolMessageKey": target_key,
                        },
                    ],
                },
                [],
                {},
                {},
                {},
                "indexeddb",
                "decrypted",
            )

            conn = sqlite3.connect(db_path)
            msg_row = conn.execute(
                """
                SELECT is_edited, edited_at, edit_count, edit_history_status
                FROM messages WHERE msg_key = ?
                """,
                (target_key,),
            ).fetchone()
            edit_row = conn.execute(
                """
                SELECT target_msg_key, edit_event_msg_key, edit_index, edited_at,
                       new_text, source, confidence
                FROM message_edits WHERE target_msg_key = ?
                """,
                (target_key,),
            ).fetchone()
            metrics = waren6.validate_unified_database(db_path)["metrics"]
            conn.close()

        self.assertEqual(msg_row, (1, 1770000100, 1, "event_history"))
        self.assertEqual(edit_row, (
            target_key,
            edit_key,
            1,
            1770000100,
            "new text",
            "store8",
            "high",
        ))
        self.assertEqual(metrics["message_edit_protocol_events"], 1)
        self.assertEqual(metrics["message_edit_protocol_folded"], 1)

    def test_orphan_message_edit_protocol_recovers_single_target_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "unified_whatsapp.db"
            target_key = "false_fixturegroup@g.us_TARGET_111@lid"
            edit_key = "false_fixturegroup@g.us_EDIT_111@lid"

            waren6.build_unified_db(
                str(db_path),
                {
                    "message": [
                        {
                            "id": edit_key,
                            "t": 1770000100,
                            "type": "protocol",
                            "subtype": "message_edit",
                            "body": "recovered edited text",
                            "protocolMessageKey": target_key,
                        },
                    ],
                },
                [],
                {},
                {},
                {},
                "indexeddb",
                "decrypted",
            )

            conn = sqlite3.connect(db_path)
            recovered = conn.execute(
                """
                SELECT msg_key, msg_id, chat_jid, text, source_recovery,
                       is_edited, edit_count, edit_history_status
                FROM messages
                WHERE msg_key = ?
                """,
                (target_key,),
            ).fetchone()
            visible_protocol_count = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE msg_key = ? AND msg_type = 'protocol'",
                (edit_key,),
            ).fetchone()[0]
            metrics = waren6.validate_unified_database(db_path)["metrics"]
            conn.close()

        self.assertEqual(recovered, (
            target_key,
            "TARGET",
            "fixturegroup@g.us",
            "recovered edited text",
            "store8_message_edit_orphan",
            1,
            1,
            "event_only_orphan",
        ))
        self.assertEqual(visible_protocol_count, 1)
        self.assertEqual(metrics["message_edit_protocol_orphans"], 1)

    def test_reply_to_edited_message_keeps_captured_quote_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "unified_whatsapp.db"
            original_key = "true_12345@c.us_ORIG"
            reply_key = "false_12345@c.us_REPLY"

            waren6.build_unified_db(
                str(db_path),
                {
                    "message": [
                        {
                            "id": original_key,
                            "t": 1770000000,
                            "type": "chat",
                            "body": "edited current text",
                            "latestEditMsgKey": "true_12345@c.us_EDIT",
                            "latestEditSenderTimestampMs": 1770000100000,
                        },
                        {
                            "id": reply_key,
                            "t": 1770000200,
                            "type": "chat",
                            "body": "reply",
                            "quotedStanzaID": "ORIG",
                            "quotedMsg": {"body": "captured original quote"},
                        },
                    ],
                },
                [],
                {},
                {},
                {},
                "indexeddb",
                "decrypted",
            )

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT quoted_msg_body FROM messages WHERE msg_key = ?",
                (reply_key,),
            ).fetchone()
            conn.close()

        self.assertEqual(row[0], "captured original quote")

    def test_message_mentions_schema_extracts_store8_mentions(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "unified_whatsapp.db"
            msg_key = "false_fixturegroup@g.us_MSG_222@lid"

            waren6.build_unified_db(
                str(db_path),
                {
                    "message": [
                        {
                            "id": msg_key,
                            "t": 1770000000,
                            "type": "chat",
                            "body": "@~Example Member Amit @all",
                            "mentionedJidList": ["111@lid", "@all"],
                        }
                    ],
                },
                [],
                {"111@lid": "910000000001@c.us"},
                {"111@lid": "Example Member"},
                {},
                "indexeddb",
                "decrypted",
            )

            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                """
                SELECT msg_key, mention_index, kind, target_jid, target_phone,
                       target_name, display_text, source, confidence
                FROM message_mentions
                ORDER BY mention_index
                """
            ).fetchall()
            conn.close()

        self.assertEqual(rows, [
            (msg_key, 0, "participant", "111@lid", "910000000001", "Example Member", None, "store8", "high"),
            (msg_key, 1, "all", None, None, None, "@all", "store8", "high"),
        ])

    def test_message_mentions_ignore_null_fields_inside_mention_objects(self):
        record = {
            "body": "hello",
            "mentionedJidList": [
                {
                    "kind": None,
                    "type": None,
                    "displayText": None,
                    "jid": {"user": "910000000003", "server": "s.whatsapp.net"},
                }
            ],
        }

        self.assertEqual(
            waren6.extract_message_mentions(record),
            [
                {
                    "kind": "participant",
                    "target_jid": "910000000003@s.whatsapp.net",
                    "display_text": None,
                }
            ],
        )

    def test_runtime_only_mentions_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "unified_whatsapp.db"
            runtime_key = "false_fixturegroup@g.us_REPLY_222@lid"
            runtime = {
                "summary": {"enabled": True, "path": "runtime.jsonl", "usable_records": 1},
                "records_by_msg_key": {
                    runtime_key: {
                        "msg_key": runtime_key,
                        "timestamp": 1770000010,
                        "type": "chat",
                        "from_me": False,
                        "chat_jid": "fixturegroup@g.us",
                        "sender_jid": "222@lid",
                        "body": "@910000000002 hello",
                        "mentioned_jids": ["910000000002@s.whatsapp.net"],
                    },
                },
            }

            waren6.build_unified_db(
                str(db_path),
                {"message": []},
                [],
                {},
                {},
                {},
                "indexeddb",
                "decrypted",
                runtime_store8_supplement=runtime,
            )

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                """
                SELECT kind, target_jid, target_phone, source, confidence
                FROM message_mentions
                WHERE msg_key = ?
                """,
                (runtime_key,),
            ).fetchone()
            conn.close()

        self.assertEqual(row, ("participant", "910000000002@s.whatsapp.net", "910000000002", "runtime", "high"))

    def test_group_metadata_subject_updates_chat_display_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "unified_whatsapp.db"
            group_jid = "fixturegroup@g.us"

            waren6.build_unified_db(
                str(db_path),
                {
                    "chat": [
                        {"id": group_jid, "name": "Old Group Name", "t": 1778494158},
                    ],
                    "group-metadata": [
                        {
                            "id": group_jid,
                            "subject": "Example Study Group",
                            "desc": "Class group",
                            "creation": 1778485570,
                        }
                    ],
                    "message": [],
                },
                [],
                {},
                {},
                {},
                "indexeddb",
                "decrypted",
            )

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT chat_name, is_group, is_newsletter FROM chats WHERE chat_jid = ?",
                (group_jid,),
            ).fetchone()
            group_row = conn.execute(
                "SELECT subject FROM groups WHERE group_jid = ?",
                (group_jid,),
            ).fetchone()
            conn.close()

        self.assertEqual(row, ("Example Study Group", 1, 0))
        self.assertEqual(group_row, ("Example Study Group",))


class MediaIndexTests(unittest.TestCase):
    def _index_audio(self, messages, name="28", content=b"voice bytes"):
        with tempfile.TemporaryDirectory() as tmp:
            case_root = Path(tmp)
            folder = case_root / "EBWebView_Default" / "IndexedDB" / "wa.indexeddb.blob"
            folder.mkdir(parents=True)
            (folder / name).write_bytes(content)
            db_path = case_root / "unified_whatsapp.db"
            conn = sqlite3.connect(db_path)
            conn.executescript(waren6.UNIFIED_SCHEMA)
            conn.executemany("""
                INSERT INTO messages(msg_key, chat_jid, timestamp, msg_type,
                    media_filename, media_mime_type, media_filehash, media_size)
                VALUES (?, ?, 1, 'audio', ?, 'audio/ogg', ?, ?)
            """, messages)
            conn.commit()
            conn.close()
            report = waren6.index_local_media_assets(db_path, case_root)
            conn = sqlite3.connect(db_path)
            rows = conn.execute("SELECT msg_key,media_case_path,media_sha256 FROM messages ORDER BY msg_key").fetchall()
            conn.close()
            return report, rows

    def test_voice_without_filename_links_only_verified_content_hash(self):
        digest = waren6.sha256_bytes(b"voice bytes")
        report, rows = self._index_audio([("voice-id", "a@lid", None, digest, 11)])
        self.assertEqual(report["messages_with_local_media"], 1)
        self.assertEqual(rows[0][2], digest)
        self.assertTrue(rows[0][1].endswith("28"))

    def test_matching_filename_never_overrides_content_hash_or_size(self):
        for expected_hash, size in ((waren6.sha256_bytes(b"other voice"), 11),
                                    (waren6.sha256_bytes(b"voice bytes"), 200)):
            with self.subTest(size=size):
                report, rows = self._index_audio([("voice-id", "a@lid", "28", expected_hash, size)])
                self.assertEqual(report["messages_with_local_media"], 0)
                self.assertIsNone(rows[0][1])

    def test_ambiguous_filename_without_hash_never_links(self):
        report, rows = self._index_audio([("first", "a@lid", "28", None, 11),
                                         ("second", "b@lid", "28", None, 11)])
        self.assertEqual(report["messages_with_local_media"], 0)
        self.assertTrue(all(row[1] is None for row in rows))

    def test_forwarded_content_can_link_multiple_exact_message_hashes(self):
        digest = waren6.sha256_bytes(b"voice bytes")
        report, rows = self._index_audio([("first", "a@lid", None, digest, 11),
                                         ("second", "b@lid", None, digest, 11)])
        self.assertEqual(report["messages_with_local_media"], 2)
        self.assertTrue(all(row[2] == digest for row in rows))

    def test_media_index_links_local_transfer_file_by_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_root = Path(tmp)
            media_dir = case_root / "sessions" / "S1" / "transfers" / "2026-19"
            media_dir.mkdir(parents=True)
            media_file = media_dir / "photo.jpg"
            media_file.write_bytes(b"fake jpg")

            db_path = case_root / "unified_whatsapp.db"
            conn = sqlite3.connect(db_path)
            conn.executescript(waren6.UNIFIED_SCHEMA)
            conn.execute(
                """
                INSERT INTO messages(
                    msg_key, chat_jid, timestamp, msg_type, media_filename,
                    media_mime_type, source, source_id, body_status, media_status
                )
                VALUES ('false_0@c.us_A', '0@c.us', 1, 'image', 'photo.jpg',
                        'image/jpeg', 'indexeddb', 'A', 'media_only', 'metadata_only')
                """
            )
            conn.commit()
            conn.close()

            report = waren6.index_local_media_assets(db_path, case_root, enabled=True)
            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT media_status, media_case_path, media_sha256 FROM messages WHERE msg_key='false_0@c.us_A'"
            ).fetchone()
            asset_count = conn.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0]
            conn.close()

        self.assertEqual(report["messages_with_local_media"], 1)
        self.assertEqual(asset_count, 1)
        self.assertEqual(row[0], "local_present")
        self.assertTrue(row[1].endswith("photo.jpg"))
        self.assertEqual(row[2], waren6.sha256_bytes(b"fake jpg"))


class MediaAcquisitionMetadataTests(unittest.TestCase):
    def test_backfill_epoch_selects_explicit_scope_and_invalid_values_keep_default(self):
        now = 1791446400
        with patch.dict(waren6.os.environ, {"WHATMCP_AUDIO_BACKFILL_AFTER": "1784766189"}):
            self.assertEqual(waren6.audio_acquisition_cutoff(now), 1784766189)
        for value in ("", "not-an-epoch", "0", "-1", str(now + 1)):
            with self.subTest(value=value), patch.dict(waren6.os.environ, {"WHATMCP_AUDIO_BACKFILL_AFTER": value}):
                self.assertEqual(waren6.audio_acquisition_cutoff(now), now - 7 * 86400)

    def test_backfill_includes_audio_after_iphone_boundary_only(self):
        import base64
        cutoff = 1784766189
        key = base64.b64encode(b"k" * 32).decode("ascii")
        digest = waren6.sha256_bytes(b"voice bytes")
        records = [
            {"id": "false_a@lid_NEW", "t": cutoff + 1, "type": "audio", "filehash": digest, "mediaKey": key},
            {"id": "false_a@lid_OLDER", "t": cutoff - 1, "type": "audio", "filehash": digest, "mediaKey": key},
        ]
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(waren6.os.environ, {"WHATMCP_AUDIO_BACKFILL_AFTER": str(cutoff)}), \
                patch.object(waren6, "acquire_audio_from_private_metadata") as acquisition:
            db_path = str(Path(tmp) / "unified_whatsapp.db")
            with contextlib.redirect_stdout(io.StringIO()):
                waren6.build_unified_db(db_path, {"message": records}, [], {}, {}, {}, "indexeddb", "decrypted")
            conn = sqlite3.connect(db_path)
            rows = conn.execute("SELECT msg_id,media_filehash,media_key FROM messages ORDER BY msg_id").fetchall()
            conn.close()
        self.assertEqual(rows, [("NEW", digest, None), ("OLDER", None, None)])
        self.assertEqual(len(acquisition.call_args.args[1]), 1)
        self.assertEqual(acquisition.call_args.args[1][0][6], "false_a@lid_NEW")

    def test_persists_hashes_and_passes_keys_only_in_memory_by_exact_message(self):
        import base64
        digest = waren6.sha256_bytes(b"voice bytes")
        b64_hash = base64.b64encode(bytes.fromhex(digest)).decode("ascii")
        key = base64.b64encode(b"k" * 32).decode("ascii")
        msg_key = "false_a@lid_EXACT"
        record = {"id": msg_key, "t": int(waren6.time.time()), "type": "audio", "mimetype": "audio/ogg",
                  "size": 11, "filehash": b64_hash, "encFilehash": b64_hash, "mediaKey": key,
                  "directPath": "/audio/example.enc", "staticUrl": "https://mmg.whatsapp.net/audio/example.enc",
                  "duration": 5}
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "unified_whatsapp.db")
            with contextlib.redirect_stdout(io.StringIO()), patch.object(waren6, "acquire_audio_from_private_metadata") as acquisition:
                waren6.build_unified_db(db_path, {"message": [record]}, [], {}, {}, {}, "indexeddb", "decrypted")
            conn = sqlite3.connect(db_path)
            row = conn.execute("SELECT media_filename,media_filehash,media_enc_filehash,media_key,media_direct_path,media_url,media_duration FROM messages WHERE msg_key=?", (msg_key,)).fetchone()
            conn.close()
        self.assertEqual(row, (None, digest, digest, None, None, None, 5))
        self.assertEqual(acquisition.call_args.args[1][0],
                         (digest, digest, key, record["directPath"], record["staticUrl"], 5, msg_key, "a@lid"))

    def test_fixed_decoder_receives_pipe_metadata_and_logs_counters_only(self):
        import json
        from types import SimpleNamespace
        metadata = [("hash", "encrypted-hash", "private-key", "/private-path", "private-url", 5,
                     "false_a@lid_EXACT", "a@lid")]
        output = io.StringIO()
        response = SimpleNamespace(returncode=0, stderr="private-key", stdout=json.dumps(
            {"downloaded": 1, "eligible": 1, "private_url": "private-url", "media_key": "private-key"}))
        from unittest.mock import MagicMock
        source = MagicMock()
        source.execute.return_value.fetchall.return_value = [("EXACT", "a@lid")]
        with patch.dict(waren6.os.environ, {"WHATMCP_AUDIO_ACQUISITION_ENABLED": "1"}), \
                patch.object(waren6.pathlib.Path, "is_file", return_value=True), \
                patch.object(waren6.pathlib.Path, "is_symlink", return_value=False), \
                patch.object(waren6.sqlite3, "connect", return_value=source), \
                patch.object(waren6.subprocess, "run", return_value=response) as run, \
                contextlib.redirect_stdout(output):
            waren6.acquire_audio_from_private_metadata("source.db", metadata)
        command = run.call_args.args[0]
        self.assertEqual(command[0].replace("\\", "/"), "C:/Program Files/nodejs/node.exe")
        self.assertTrue(command[4].replace("\\", "/").endswith("/whatmcp/scripts/acquire-windows-audio.ts"))
        self.assertEqual(command[5:], ["--source=source.db", "--metadata-stdin"])
        self.assertEqual(json.loads(run.call_args.kwargs["input"])[0]["msg_id"], "EXACT")
        self.assertEqual(json.loads(run.call_args.kwargs["input"])[0]["media_key"], "private-key")
        self.assertNotIn("private-key", output.getvalue())
        self.assertNotIn("private-url", output.getvalue())
        self.assertIn('"downloaded": 1', output.getvalue())

    def test_pipe_limits_recent_and_backfill_candidates_before_serializing_keys(self):
        import json
        from types import SimpleNamespace
        now = int(waren6.time.time())
        metadata = [("ab" * 32, None, "private-key", "/audio.enc", None, 5,
                     f"false_a@lid_ID{i}", "a@lid") for i in range(2001)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.db"
            conn = sqlite3.connect(path)
            conn.executescript(waren6.UNIFIED_SCHEMA)
            conn.executemany("""INSERT INTO messages(msg_id,chat_jid,timestamp,msg_type,media_filehash)
                VALUES (?, 'a@lid', ?, 'audio', ?)""",
                [(f"ID{i}", now, "ab" * 32) for i in range(2001)])
            conn.commit()
            conn.close()
            for after, limit in (("", 200), (str(now - 90 * 86400), 2000)):
                with self.subTest(limit=limit), \
                        patch.dict(waren6.os.environ, {"WHATMCP_AUDIO_ACQUISITION_ENABLED": "1", "WHATMCP_AUDIO_BACKFILL_AFTER": after}), \
                        patch.object(waren6.pathlib.Path, "is_file", return_value=True), \
                        patch.object(waren6.pathlib.Path, "is_symlink", return_value=False), \
                        patch.object(waren6.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout='{"eligible":0}', stderr="")) as run, \
                        contextlib.redirect_stdout(io.StringIO()):
                    waren6.acquire_audio_from_private_metadata(path, metadata)
                payload = json.loads(run.call_args.kwargs["input"])
                self.assertEqual(len(payload), limit)
                self.assertEqual(payload[0]["msg_id"], "ID2000")
                self.assertEqual(payload[-1]["msg_id"], f"ID{2001-limit}")
            conn = sqlite3.connect(path)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM messages WHERE media_key IS NOT NULL").fetchone()[0], 0)
            conn.close()

    def test_acquisition_secrets_are_not_retained_for_images_or_old_audio(self):
        import base64
        key = base64.b64encode(b"k" * 32).decode("ascii")
        records = [
            {"id": "false_a@lid_IMAGE", "t": int(waren6.time.time()), "type": "image", "mediaKey": key},
            {"id": "false_a@lid_OLD", "t": 10, "type": "audio", "mediaKey": key},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "unified_whatsapp.db")
            with contextlib.redirect_stdout(io.StringIO()):
                waren6.build_unified_db(db_path, {"message": records}, [], {}, {}, {}, "indexeddb", "decrypted")
            conn = sqlite3.connect(db_path)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM messages WHERE media_key IS NOT NULL OR media_url IS NOT NULL").fetchone()[0], 0)
            conn.close()

    def test_runtime_supplement_metadata_fills_missing_store8_metadata(self):
        import base64
        digest = waren6.sha256_bytes(b"voice bytes")
        key = base64.b64encode(b"k" * 32).decode("ascii")
        metadata = waren6.media_acquisition_metadata({"filehash": None},
            {"filehash": digest, "media_key": key, "direct_path": "/audio/example.enc", "media_size": 11})
        self.assertEqual(metadata[0], digest)
        self.assertEqual(metadata[2], key)
        self.assertEqual(metadata[3], "/audio/example.enc")
        self.assertIsNone(waren6.media_digest_bytes("invalid hash"))


class UnifyPathTests(unittest.TestCase):
    def test_prepare_unify_case_accepts_zip_and_creates_output_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = root / "WAren6_20260509120000"
            (case / "EBWebView_Default" / "IndexedDB").mkdir(parents=True)
            zip_base = root / "case_archive"
            archive = shutil.make_archive(str(zip_base), "zip", root, case.name)

            prepared = waren6.prepare_unify_case(archive)

            self.assertTrue(str(prepared["output"]).endswith("case_archive_unified\\unified_whatsapp.db") or
                            str(prepared["output"]).endswith("case_archive_unified/unified_whatsapp.db"))
            self.assertTrue(prepared["idb_path"].exists())
            self.assertTrue(prepared["extracted_from_zip"])

    def test_cleanup_prepared_unify_case_removes_unzipped_source_after_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = root / "WAren6_20260509120000"
            (case / "EBWebView_Default" / "IndexedDB").mkdir(parents=True)
            archive = shutil.make_archive(str(root / "case_archive"), "zip", root, case.name)

            prepared = waren6.prepare_unify_case(archive)
            extract_root = Path(prepared["extract_root"])
            self.assertTrue(extract_root.exists())

            waren6.cleanup_prepared_unify_case(prepared, success=True)

            self.assertFalse(extract_root.exists())

    def test_cleanup_prepared_unify_case_preserves_unzipped_source_after_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = root / "WAren6_20260509120000"
            (case / "EBWebView_Default" / "IndexedDB").mkdir(parents=True)
            archive = shutil.make_archive(str(root / "case_archive"), "zip", root, case.name)

            prepared = waren6.prepare_unify_case(archive)
            extract_root = Path(prepared["extract_root"])
            waren6.cleanup_prepared_unify_case(prepared, success=False)

            self.assertTrue(extract_root.exists())

    def test_prepare_unify_case_accepts_tar_zst_archive_when_system_tar_supports_it(self):
        if not shutil.which("tar"):
            self.skipTest("system tar unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = root / "WAren6_20260509120000"
            (case / "EBWebView_Default" / "IndexedDB").mkdir(parents=True)
            archive = root / "case_archive.tar.zst"
            try:
                import subprocess

                subprocess.run(
                    ["tar", "--zstd", "-cf", str(archive), "-C", str(root), case.name],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except Exception as exc:
                self.skipTest(f"system tar lacks zstd support: {exc}")

            prepared = waren6.prepare_unify_case(archive)

            self.assertTrue(prepared["idb_path"].exists())
            self.assertTrue(Path(prepared["extract_root"]).exists())
            waren6.cleanup_prepared_unify_case(prepared, success=True)
            self.assertFalse(Path(prepared["extract_root"]).exists())


if __name__ == "__main__":
    unittest.main()
