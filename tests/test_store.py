import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from usage_store import UsageStore
from app import page


class StoreTest(unittest.TestCase):
    def test_incremental_history_forks_resets_partial_lines_and_models(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sessions = root / "sessions"
            sessions.mkdir()
            now = time.time()
            def stamp(value):
                return datetime.fromtimestamp(value, timezone.utc).isoformat()
            def event(when, total, last):
                return dict(timestamp=stamp(when), type="event_msg", payload=dict(type="token_count", info=dict(
                    total_token_usage=dict(input_tokens=total, total_tokens=total),
                    last_token_usage=dict(input_tokens=last, total_tokens=last))))
            meta = dict(type="session_meta", payload=dict(id="original", cwd="D:\\work\\demo", timestamp=stamp(now-6*86400)))
            context = dict(type="turn_context", payload=dict(model="model-a"))
            old = event(now-9*86400, 1000, 1000)
            two_days = event(now-2*86400, 1100, 100)
            recent = event(now-1800, 1150, 50)
            reset = event(now-60, 20, 20)
            path = sessions / "z-original.jsonl"
            lines = [meta, context, old, two_days, recent, recent, reset]
            path.write_text("\n".join(map(json.dumps, lines))+"\n")
            copied = dict(type="session_meta", payload=dict(id="copied", cwd="D:\\work\\demo", timestamp=stamp(now-86400)))
            (sessions/"a-copied.jsonl").write_text("\n".join(map(json.dumps, [copied,context,old,two_days,recent,reset]))+"\n")
            config = dict(codex_root=str(root),cache_dir=str(root/"cache"),quota_dir=None,
                          timezone_offset=480,timezone="+08:00",refresh_seconds=60)
            store = UsageStore(config)
            def total(data, hours):
                return sum(t["total"] for i in data["views"][str(hours)]["intervals"] for t in i["tasks"])
            first = store.snapshot(force=True,now=now)
            self.assertEqual(total(first,24),70)
            self.assertEqual(total(first,168),170)
            self.assertEqual({t["id"] for i in first["views"]["168"]["intervals"] for t in i["tasks"]},{"original"})
            idle = store.snapshot(force=True,now=now)
            self.assertEqual(idle["scan"]["bytesRead"],0)
            with path.open("a") as f:
                f.write(json.dumps(event(now-10,30,10)))
            partial = store.snapshot(force=True,now=now)
            self.assertEqual(total(partial,24),70)
            with path.open("a") as f:
                f.write("\n")
                f.write(json.dumps(dict(type="turn_context",payload=dict(model="model-b")))+"\n")
                f.write(json.dumps(event(now-5,50,20))+"\n")
            updated = store.snapshot(force=True,now=now)
            self.assertEqual(total(updated,24),100)
            self.assertEqual(total(updated,168),200)
            self.assertLess(updated["scan"]["bytesRead"],path.stat().st_size)
            self.assertEqual(len(updated["views"]["168"]["intervals"]),169)
            self.assertTrue(all(i["start"]>=updated["views"]["24"]["start"] and i["end"]<=updated["views"]["24"]["end"] for i in updated["views"]["24"]["intervals"]))
            html = page(updated)
            self.assertNotIn("__BOOTSTRAP__",html)
            self.assertNotIn("/*__SCRIPT__*/",html)
            self.assertIn('"version":1',html)
            store.close()
            reopened = UsageStore(config)
            same = reopened.snapshot(force=True,now=now)
            self.assertEqual(total(same,24),100)
            self.assertEqual(same["scan"]["bytesRead"],0)
            reopened.close()

    def test_empty_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/"sessions").mkdir()
            store=UsageStore(dict(codex_root=str(root),cache_dir=str(root/"cache"),quota_dir=None,
                                  timezone_offset=480,timezone="+08:00",refresh_seconds=60))
            data=store.snapshot()
            self.assertIsNone(data["views"]["24"]["lastEvent"])
            self.assertEqual(data["quota"],[])
            store.close()


class EffortStoreTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.sessions = self.root / "sessions"
        self.sessions.mkdir()
        # Keep all sample events in the same hour to exercise SQL grouping.
        self.now = int(time.time() // 3600) * 3600 + 600
        self.config = dict(codex_root=str(self.root), cache_dir=str(self.root / "cache"),
                           quota_dir=None, timezone_offset=480, timezone="+08:00", refresh_seconds=60)

    def store(self):
        store = UsageStore(self.config)
        self.addCleanup(store.close)
        return store

    def stamp(self, when):
        return datetime.fromtimestamp(when, timezone.utc).isoformat()

    def meta(self, thread="original", created=None):
        return dict(type="session_meta", payload=dict(id=thread, cwd="D:/work/demo",
                    timestamp=self.stamp(self.now - 1000 if created is None else created)))

    def context(self, **values):
        return dict(type="turn_context", payload=dict(model="gpt-6-astra", **values))

    def event(self, when, cumulative, last):
        def usage(value):
            return dict(input_tokens=value, cached_input_tokens=value // 2,
                        output_tokens=value // 4, reasoning_output_tokens=value // 5,
                        total_tokens=value + value // 4)
        return dict(timestamp=self.stamp(when), type="event_msg", payload=dict(type="token_count",
                    info=dict(total_token_usage=usage(cumulative), last_token_usage=usage(last))))

    def write(self, name, rows, mode="w"):
        path = self.sessions / name
        with path.open(mode, encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row) + "\n")
        return path

    def tasks(self, data):
        return [task for interval in data["views"]["24"]["intervals"] for task in interval["tasks"]]

    def by_effort(self, data):
        grouped = {}
        for task in self.tasks(data):
            values = grouped.setdefault(task["effort"], dict(input=0, cached=0, output=0, reasoning=0, total=0))
            for field in values:
                values[field] += task[field]
        return grouped

    def downgrade_cache(self, store):
        # Reproduce the pre-effort schema and exact cached file offsets/metadata.
        with store.db:
            store.db.execute("ALTER TABLE events RENAME TO current_events")
            store.db.execute("""CREATE TABLE events(
                fingerprint TEXT PRIMARY KEY, ts REAL NOT NULL, thread TEXT NOT NULL,
                model TEXT, project TEXT, input INTEGER, cached INTEGER, output INTEGER,
                reasoning INTEGER, total INTEGER, source_created REAL)""")
            store.db.execute("""INSERT INTO events SELECT fingerprint,ts,thread,model,project,
                input,cached,output,reasoning,total,source_created FROM current_events""")
            store.db.execute("DROP TABLE current_events")
            for path, state in list(store.db.execute("SELECT path,state FROM files")):
                state = json.loads(state)
                state.pop("effort", None)
                state.pop("index_version", None)
                store.db.execute("UPDATE files SET state=? WHERE path=?", (json.dumps(state), path))
            store.db.execute("DELETE FROM meta WHERE key='schema_version'")

    def test_same_model_effort_switches_keep_cumulative_tokens(self):
        last = self.event(self.now - 300, 160, 20)
        self.write("sample.jsonl", [self.meta(), self.context(effort=" Ultra "),
                   self.event(self.now - 500, 100, 100), self.context(effort="medium"),
                   self.event(self.now - 400, 140, 40), self.context(effort="ultra"), last, last])
        data = self.store().snapshot(force=True, now=self.now)
        self.assertEqual(len(self.tasks(data)), 2)
        self.assertEqual(self.by_effort(data), {
            "ultra": dict(input=120, cached=60, output=30, reasoning=24, total=150),
            "medium": dict(input=40, cached=20, output=10, reasoning=8, total=50)})
        self.assertEqual({task["model"] for task in self.tasks(data)}, {"gpt-6-astra"})

    def test_unknown_resets_and_nested_fallback(self):
        contexts = [None, self.context(effort="ultra"), self.context(),
                    self.context(collaboration_mode=dict(settings=dict(reasoning_effort=" Medium "))),
                    self.context(effort=None, collaboration_mode=dict(settings=dict(reasoning_effort="high"))),
                    self.context(effort=4, collaboration_mode=dict(settings=dict(reasoning_effort="xhigh"))),
                    self.context(effort=" HIGH ", collaboration_mode=dict(settings=dict(reasoning_effort="medium"))),
                    self.context(collaboration_mode=dict(settings=[])), self.context(effort=" ")]
        rows = [self.meta()]
        for index, context in enumerate(contexts):
            if context:
                rows.append(context)
            rows.append(self.event(self.now - 500 + index, (index + 1) * 20, 20))
        self.write("sample.jsonl", rows)
        grouped = self.by_effort(self.store().snapshot(force=True, now=self.now))
        self.assertEqual({effort: values["input"] for effort, values in grouped.items()},
                         dict(ultra=20, medium=20, high=20, unknown=120))
        self.assertEqual(sum(values["total"] for values in grouped.values()), 225)

    def test_incremental_effort_survives_reopening(self):
        path = self.write("sample.jsonl", [self.meta(), self.context(effort="ultra"),
                          self.event(self.now - 500, 100, 100)])
        first = UsageStore(self.config)
        try:
            first.snapshot(force=True, now=self.now)
        finally:
            first.close()
        store = self.store()
        self.assertEqual(store.snapshot(force=True, now=self.now)["scan"]["bytesRead"], 0)
        self.write(path.name, [self.event(self.now - 400, 140, 40), self.context(effort="medium"),
                              self.event(self.now - 300, 160, 20)], mode="a")
        data = store.snapshot(force=True, now=self.now)
        self.assertEqual({effort: row["input"] for effort, row in self.by_effort(data).items()},
                         dict(ultra=140, medium=20))
        self.assertLess(data["scan"]["bytesRead"], path.stat().st_size)
        state = json.loads(store.db.execute("SELECT state FROM files").fetchone()[0])
        self.assertEqual(state["effort"], "medium")
        self.assertEqual(state["index_version"], 2)

    def test_legacy_cache_backfills_unchanged_logs_and_preserves_fork_dedup(self):
        history = [self.context(effort="ultra"), self.event(self.now - 500, 100, 100),
                   self.context(effort="medium"), self.event(self.now - 400, 120, 20)]
        original = self.write("z-original.jsonl", [self.meta(), *history])
        copied = self.write("a-copy.jsonl", [self.meta("copied", self.now - 700), *history])
        before = {path: path.read_bytes() for path in (original, copied)}
        first = UsageStore(self.config)
        try:
            initial = first.snapshot(force=True, now=self.now)
            self.downgrade_cache(first)
            # Old filesystem mtimes must not cause a tracked file to be skipped.
            for path in (original, copied):
                os.utime(path, (self.now - 9 * 86400, self.now - 9 * 86400))
                first.db.execute("UPDATE files SET mtime=? WHERE path=?", (path.stat().st_mtime_ns, str(path)))
            first.db.commit()
        finally:
            first.close()
        metadata = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in before}
        store = self.store()
        migrated = store.snapshot(force=True, now=self.now)
        self.assertEqual(self.by_effort(migrated), self.by_effort(initial))
        self.assertEqual({task["id"] for task in self.tasks(migrated)}, {"original"})
        self.assertEqual(sum(task["total"] for task in self.tasks(migrated)), 150)
        self.assertEqual(migrated["scan"]["bytesRead"], sum(len(data) for data in before.values()))
        self.assertEqual(store.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], "2")
        self.assertEqual(store.snapshot(force=True, now=self.now)["scan"]["bytesRead"], 0)
        for path, contents in before.items():
            self.assertEqual(path.read_bytes(), contents)
            self.assertEqual((path.stat().st_size, path.stat().st_mtime_ns), metadata[path])

    def test_appended_legacy_log_without_metadata_preserves_creation_time(self):
        path = self.write("sample.jsonl", [self.context(effort="ultra"),
                          self.event(self.now - 500, 100, 100)])
        first = UsageStore(self.config)
        try:
            first.snapshot(force=True, now=self.now)
            self.downgrade_cache(first)
        finally:
            first.close()
        initial_mtime = path.stat().st_mtime
        self.write(path.name, [self.context(effort="medium"), self.event(self.now - 400, 140, 40)], mode="a")
        os.utime(path, (initial_mtime + 10, initial_mtime + 10))
        store = self.store()
        grouped = self.by_effort(store.snapshot(force=True, now=self.now))
        self.assertEqual({effort: values["input"] for effort, values in grouped.items()}, dict(ultra=100, medium=40))
        self.assertEqual({row[0] for row in store.db.execute("SELECT source_created FROM events")}, {initial_mtime})

    def test_failed_legacy_backfill_retains_totals_and_retries(self):
        path = self.write("sample.jsonl", [self.meta(), self.context(effort="ultra"),
                          self.event(self.now - 500, 100, 100)])
        first = UsageStore(self.config)
        try:
            first.snapshot(force=True, now=self.now)
            self.downgrade_cache(first)
        finally:
            first.close()
        store = self.store()
        real_open = Path.open
        def cannot_read(log, *args, **kwargs):
            if log == path and args and args[0] == "rb":
                raise PermissionError("temporarily unavailable")
            return real_open(log, *args, **kwargs)
        with patch.object(Path, "open", cannot_read):
            unavailable = store.snapshot(force=True, now=self.now)
        self.assertEqual(self.by_effort(unavailable)["unknown"]["total"], 125)
        self.assertTrue(unavailable["warnings"])
        recovered = store.snapshot(force=True, now=self.now)
        self.assertEqual(self.by_effort(recovered)["ultra"]["total"], 125)
        self.assertEqual(recovered["scan"]["bytesRead"], path.stat().st_size)

    def test_interrupted_legacy_backfill_rolls_back_and_retries(self):
        path = self.write("sample.jsonl", [self.meta(), self.context(effort="ultra"),
                          self.event(self.now - 500, 100, 100)])
        first = UsageStore(self.config)
        try:
            first.snapshot(force=True, now=self.now)
            self.downgrade_cache(first)
        finally:
            first.close()
        store = self.store()
        real_open = Path.open
        def interrupted(log, *args, **kwargs):
            if log == path and args and args[0] == "rb":
                raise RuntimeError("interrupted refresh")
            return real_open(log, *args, **kwargs)
        with patch.object(Path, "open", interrupted):
            with self.assertRaisesRegex(RuntimeError, "interrupted refresh"):
                store.snapshot(force=True, now=self.now)
        self.assertEqual(store.db.execute("SELECT effort,total FROM events").fetchall(), [("unknown", 125)])
        state = json.loads(store.db.execute("SELECT state FROM files").fetchone()[0])
        self.assertNotIn("index_version", state)
        self.assertEqual(self.by_effort(store.snapshot(force=True, now=self.now))["ultra"]["total"], 125)


if __name__=="__main__":
    unittest.main()
