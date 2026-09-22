import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src/statistics"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src/dashboard"))
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


class CustomRangeTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.sessions = self.root / "sessions"
        self.sessions.mkdir()
        self.now = int(time.time() // 3600) * 3600 + 1800
        self.config = dict(codex_root=str(self.root), cache_dir=str(self.root / "cache"),
                           quota_dir=None, timezone_offset=480, timezone="+08:00", refresh_seconds=60)

    def store(self):
        store = UsageStore(self.config)
        self.addCleanup(store.close)
        return store

    def stamp(self, when):
        return datetime.fromtimestamp(when, timezone.utc).isoformat()

    def event(self, when, cumulative, last):
        def usage(value):
            return dict(input_tokens=value, total_tokens=value)
        return dict(timestamp=self.stamp(when), type="event_msg", payload=dict(type="token_count",
                    info=dict(total_token_usage=usage(cumulative), last_token_usage=usage(last))))

    def write(self, name, thread, created, events):
        path = self.sessions / name
        rows = [dict(type="session_meta", payload=dict(id=thread, timestamp=self.stamp(created))),
                dict(type="turn_context", payload=dict(model="gpt-6-astra", effort="ultra")), *events]
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return path

    def total(self, data, view="custom"):
        return sum(task["total"] for interval in data["views"][view]["intervals"] for task in interval["tasks"])

    def test_custom_boundaries_partial_hours_and_exact_end_exclusion(self):
        hour = self.now - 10 * 86400 - 1800
        start, end = hour + 600.125, hour + 4500.250
        times = [start - .001, start, hour + 3600, end - .001, end, end + .001]
        rows = [self.event(when, (index + 1) * 100, 100) for index, when in enumerate(times)]
        self.write("boundary.jsonl", "boundary", hour - 60, rows)
        store = self.store()
        selected = store.snapshot(now=self.now, start=start * 1000, end=end * 1000)
        self.assertEqual(set(selected["views"]), {"24", "168", "custom"})
        view = selected["views"]["custom"]
        self.assertEqual((view["start"], view["end"]), (start * 1000, end * 1000))
        self.assertEqual(view["hours"], (end - start) / 3600)
        self.assertEqual(self.total(selected), 300)
        self.assertEqual([(i["start"], i["end"]) for i in view["intervals"]],
                         [(start * 1000, (hour + 3600) * 1000), ((hour + 3600) * 1000, end * 1000)])
        self.assertEqual((view["firstEvent"], view["lastEvent"]), (start * 1000, (end - .001) * 1000))
        next_range = store.snapshot(now=self.now, start=end * 1000, end=(end + 1) * 1000)
        self.assertEqual(self.total(next_range), 200)
        self.assertEqual(self.total(selected, "24"), 0)

    def test_history_replays_skipped_and_indexed_logs_then_remains_incremental(self):
        older, old = self.now - 30 * 86400, self.now - 20 * 86400
        history = [self.event(old, 100, 100), self.event(self.now - 60, 150, 50)]
        original = self.write("z-original.jsonl", "original", old - 60, history)
        self.write("a-copy.jsonl", "fork", old + 60, history)
        skipped = self.write("old-mtime.jsonl", "older", older - 60, [self.event(older, 200, 200)])
        os.utime(skipped, (older, older))
        first = UsageStore(self.config)
        try:
            regular = first.snapshot(force=True, now=self.now)
            self.assertEqual(self.total(regular, "168"), 50)
            self.assertEqual(first.db.execute("SELECT COUNT(*) FROM files").fetchone()[0], 2)
            self.assertFalse(first.history_enabled)
            # The custom request must bypass the two-second scan throttle.
            full = first.snapshot(now=self.now, start=(older - 1) * 1000, end=self.now * 1000)
            self.assertEqual(self.total(full), 350)
            self.assertEqual(self.total(full, "168"), 50)
            self.assertEqual({t["id"] for i in full["views"]["custom"]["intervals"] for t in i["tasks"]},
                             {"original", "older"})
            self.assertTrue(first.history_enabled)
            idle = first.snapshot(force=True, now=self.now, start=(older - 1) * 1000, end=self.now * 1000)
            self.assertEqual(idle["scan"]["bytesRead"], 0)
            self.assertEqual(self.total(idle), 350)
        finally:
            first.close()
        reopened = self.store()
        self.assertTrue(reopened.history_enabled)
        with original.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(self.event(self.now - 30, 175, 25)) + "\n")
        updated = reopened.snapshot(force=True, now=self.now, start=(older - 1) * 1000, end=self.now * 1000)
        self.assertEqual(self.total(updated), 375)
        self.assertLess(updated["scan"]["bytesRead"], original.stat().st_size)
        self.assertEqual(self.total(updated, "24"), 75)
        # Refreshing a preset much later must not prune history after custom use.
        reopened.snapshot(force=True, now=self.now + 10 * 86400)
        again = reopened.snapshot(force=True, now=self.now + 10 * 86400,
                                  start=(older - 1) * 1000, end=self.now * 1000)
        self.assertEqual(self.total(again), 375)

    def test_history_enabled_by_another_instance_is_never_pruned(self):
        old = self.now - 20 * 86400
        self.write("old.jsonl", "old", old - 60, [self.event(old, 100, 100)])
        waiting = self.store()
        indexing = self.store()
        self.assertFalse(waiting.history_enabled)
        indexing.snapshot(force=True, now=self.now, start=(old - 1) * 1000, end=self.now * 1000)
        waiting.snapshot(force=True, now=self.now + 10)
        self.assertTrue(waiting.history_enabled)
        self.assertEqual(waiting.db.execute("SELECT SUM(total) FROM events").fetchone()[0], 100)
        selected = indexing.snapshot(force=True, now=self.now + 20,
                                     start=(old - 1) * 1000, end=self.now * 1000)
        self.assertEqual(self.total(selected), 100)
        self.assertEqual(selected["scan"]["bytesRead"], 0)

    def test_epoch_range_with_negative_timezone_uses_floor_buckets(self):
        self.config.update(timezone_offset=-330, timezone="-05:30")
        self.write("epoch.jsonl", "epoch", 0, [self.event(600, 100, 100), self.event(1900, 150, 50)])
        data = self.store().snapshot(now=self.now, start=0, end=3600 * 1000)
        self.assertEqual(self.total(data), 150)
        self.assertEqual([(i["start"], i["end"]) for i in data["views"]["custom"]["intervals"]],
                         [(0, 1800 * 1000), (1800 * 1000, 3600 * 1000)])
        self.assertEqual([sum(t["total"] for t in i["tasks"]) for i in data["views"]["custom"]["intervals"]], [100, 50])

    def test_unreadable_history_keeps_recent_counts_and_retries(self):
        old = self.now - 20 * 86400
        path = self.write("retry.jsonl", "retry", old - 60,
                          [self.event(old, 100, 100), self.event(self.now - 60, 150, 50)])
        store = self.store()
        store.snapshot(force=True, now=self.now)
        real_open = Path.open
        def unavailable(log, *args, **kwargs):
            if log == path and args and args[0] == "rb":
                raise PermissionError("temporarily unavailable")
            return real_open(log, *args, **kwargs)
        args = dict(force=True, now=self.now, start=(old - 1) * 1000, end=self.now * 1000)
        with patch.object(Path, "open", unavailable):
            failed = store.snapshot(**args)
        self.assertEqual(self.total(failed), 50)
        self.assertTrue(failed["warnings"])
        self.assertFalse(json.loads(store.db.execute("SELECT state FROM files").fetchone()[0])["history_indexed"])
        recovered = store.snapshot(**args)
        self.assertEqual(self.total(recovered), 150)
        self.assertEqual(recovered["warnings"], [])
        self.assertTrue(json.loads(store.db.execute("SELECT state FROM files").fetchone()[0])["history_indexed"])

    def test_historical_names_and_quota_cover_union_with_presets(self):
        old = self.now - 20 * 86400
        self.write("old.jsonl", "historic", old - 60, [self.event(old, 100, 100)])
        self.config["quota_dir"] = str(self.root)
        rows = [dict(captured_at_utc=self.stamp(when), windows=[])
                for when in (old - 2, old, old + 2, self.now - 60)]
        (self.root / "quota-history.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        store = self.store()
        with patch.object(store, "task_names", return_value=({"historic": "旧任务"}, set())) as lookup:
            data = store.snapshot(now=self.now, start=(old - 1) * 1000, end=(old + 1) * 1000)
        self.assertEqual(lookup.call_args.args[0], {"historic"})
        task = next(t for i in data["views"]["custom"]["intervals"] for t in i["tasks"])
        self.assertEqual(task["title"], "旧任务")
        self.assertEqual([p["t"] for p in data["quota"]], [old * 1000, (self.now - 60) * 1000])

    def test_invalid_ranges_do_not_scan_and_maximum_is_inclusive(self):
        store = self.store()
        end = self.now * 1000
        invalid = [(None, end), (end - 1000, None), ("", end), ("nan", end),
                   (end - 1000, "inf"), (-1, end), (end, end), (end + 1, end),
                   (end - 367 * 86400 * 1000, end), (end, end + 61000)]
        with patch.object(store, "refresh") as refresh:
            for start, finish in invalid:
                with self.subTest(start=start, end=finish), self.assertRaises(ValueError):
                    store.snapshot(now=self.now, start=start, end=finish)
            refresh.assert_not_called()
        accepted = store.snapshot(now=self.now, start=end - 366 * 86400 * 1000, end=end)
        self.assertEqual(accepted["views"]["custom"]["hours"], 366 * 24)
        tolerated = store.snapshot(now=self.now, start=end - 1000, end=end + 60000)
        self.assertEqual(tolerated["views"]["custom"]["end"], end + 60000)


if __name__=="__main__":
    unittest.main()
