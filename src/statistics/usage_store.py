"""Incremental local log index. Does not read auth files or call APIs."""
import hashlib
import json
import math
import platform
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

FIELDS = ("input", "cached", "output", "reasoning", "total")
SCHEMA_VERSION = 2
KEYS = dict(input="input_tokens", cached="cached_input_tokens",
            output="output_tokens", reasoning="reasoning_output_tokens", total="total_tokens")


def custom_range(start, end, now):
    """Validate API milliseconds before scanning or constructing hourly buckets."""
    if start is None and end is None:
        return None
    if start is None or end is None:
        raise ValueError("请同时选择开始时间和结束时间")
    try:
        start, end = float(start), float(end)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("开始时间和结束时间必须是有效时间") from None
    if not math.isfinite(start) or not math.isfinite(end):
        raise ValueError("开始时间和结束时间必须是有效时间")
    if start < 0:
        raise ValueError("开始时间不能早于 1970 年")
    if start >= end:
        raise ValueError("结束时间必须晚于开始时间")
    if end - start > 366 * 86400 * 1000:
        raise ValueError("单次最多选择 366 天")
    if end / 1000 > now + 60:
        raise ValueError("结束时间不能晚于当前时间")
    return start / 1000, end / 1000


def timestamp(value):
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return date.timestamp()


def counts(value):
    return {key: max(0, int(value.get(source, 0) or 0)) for key, source in KEYS.items()}


def delta(total, previous, last):
    if previous is None or any(total.get(key, 0) < previous.get(key, 0)
                               for key in ("input_tokens", "output_tokens", "total_tokens")):
        return counts(last or {})
    return {key: max(0, int(total.get(source, 0) or 0) - int(previous.get(source, 0) or 0))
            for key, source in KEYS.items()}


def project_name(value):
    return PureWindowsPath(value).name if "\\" in value else Path(value).name


def reasoning_effort(payload):
    if "effort" in payload:
        value = payload["effort"]
    else:
        mode = payload.get("collaboration_mode")
        settings = mode.get("settings") if isinstance(mode, dict) else None
        value = settings.get("reasoning_effort") if isinstance(settings, dict) else None
    if not isinstance(value, str):
        return "unknown"
    return value.strip().lower() or "unknown"


class AccountConflict(ValueError):
    pass


class UsageStore:
    def __init__(self, config):
        self.config = config
        self.root = Path(config["codex_root"])
        if not (self.root / "sessions").is_dir() and not (self.root / "archived_sessions").is_dir():
            raise ValueError("所选 .codex 目录没有 sessions 或 archived_sessions")
        self.lock = threading.RLock()
        cache = Path(config["cache_dir"])
        cache.mkdir(parents=True, exist_ok=True)
        identity = hashlib.sha256(str(self.root.resolve()).encode()).hexdigest()[:16]
        self.db = sqlite3.connect(cache / ("usage-" + identity + ".sqlite"), timeout=30, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, size INTEGER, mtime INTEGER, state TEXT);
          CREATE TABLE IF NOT EXISTS events(
            fingerprint TEXT PRIMARY KEY, ts REAL NOT NULL, thread TEXT NOT NULL,
            model TEXT, project TEXT, input INTEGER, cached INTEGER, output INTEGER,
            reasoning INTEGER, total INTEGER, source_created REAL, effort TEXT NOT NULL DEFAULT 'unknown'
          );
          CREATE INDEX IF NOT EXISTS events_by_time ON events(ts);
          CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
        """)
        # Upgrade the cache atomically. File state versions trigger lazy backfill
        # from original logs, preserving cached totals if a log cannot be read.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in self.db.execute("PRAGMA table_info(events)")}
            if "effort" not in columns:
                self.db.execute("ALTER TABLE events ADD COLUMN effort TEXT NOT NULL DEFAULT 'unknown'")
            self.db.execute("INSERT OR REPLACE INTO meta VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
        self.history_enabled = bool(self.db.execute("SELECT 1 FROM meta WHERE key='history_enabled'").fetchone())
        # User annotations are durable data, separate from the disposable log cache.
        account_dir = Path(config.get("account_data_dir") or cache.parent / "account-data")
        account_dir.mkdir(parents=True, exist_ok=True)
        self.db.execute("ATTACH DATABASE ? AS attribution", (str(account_dir / ("accounts-" + identity + ".sqlite")),))
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS attribution.marks(start INTEGER PRIMARY KEY, account TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS attribution.settings(key TEXT PRIMARY KEY, value INTEGER NOT NULL);
          INSERT OR IGNORE INTO attribution.settings VALUES('revision',0);
        """)
        self.last_scan = 0
        self.last_result = {}
        self.initialized = bool(self.db.execute("SELECT 1 FROM meta WHERE key='initialized'").fetchone())

    def close(self):
        self.db.close()

    def refresh(self, force=False, now=None, full_history=False):
        with self.lock:
            now = time.time() if now is None else now
            history = full_history or self.history_enabled
            if not force and not (history and not self.history_enabled) and self.last_scan and now - self.last_scan < 2:
                return self.last_result
            started = time.monotonic()
            changed = read_bytes = inserted = 0
            warnings = []
            paths = []
            for folder in ("sessions", "archived_sessions"):
                directory = self.root / folder
                if directory.is_dir():
                    paths.extend(directory.rglob("*.jsonl"))
            self.db.execute("BEGIN IMMEDIATE")
            try:
                # Other running instances (including HTML export) share this cache.
                # Once any instance enables history, no instance may prune it again.
                history = history or bool(self.db.execute("SELECT 1 FROM meta WHERE key='history_enabled'").fetchone())
                cutoff = float("-inf") if history else now - 8 * 86400
                for path in sorted(paths):
                    try:
                        stat = path.stat()
                        old = self.db.execute("SELECT size,mtime,state FROM files WHERE path=?", (str(path),)).fetchone()
                        old_state = json.loads(old[2]) if old else None
                        backfill = bool(old_state and old_state.get("index_version", 1) < SCHEMA_VERSION)
                        replay = backfill or bool(history and old_state and not old_state.get("history_indexed"))
                        if old and not replay and old[0] == stat.st_size and old[1] == stat.st_mtime_ns:
                            continue
                        if not old and stat.st_mtime < cutoff:
                            continue
                        changed += 1
                        state = old_state if old and not replay else {
                            "offset": 0, "thread": path.stem, "model": "unknown", "effort": "unknown",
                            "project": "", "previous": None,
                            "created": old_state.get("created", stat.st_mtime) if replay else stat.st_mtime,
                            "index_version": SCHEMA_VERSION, "history_indexed": history}
                        if not replay and (stat.st_size < state["offset"] or (old and old[0] == stat.st_size)):
                            state = dict(offset=0, thread=path.stem, model="unknown", effort="unknown",
                                         project="", previous=None, created=stat.st_mtime,
                                         index_version=SCHEMA_VERSION, history_indexed=history)
                            warnings.append("检测到日志替换，重新读取并去重：" + path.name)
                        with path.open("rb") as stream:
                            stream.seek(state["offset"])
                            while stream.tell() < stat.st_size:
                                offset = stream.tell()
                                line = stream.readline(stat.st_size - offset)
                                read_bytes += len(line)
                                if not line.endswith(b"\n"):
                                    break
                                state["offset"] = stream.tell()
                                if not any(tag in line for tag in (b'"session_meta"', b'"turn_context"', b'"token_count"')):
                                    continue
                                try:
                                    event = json.loads(line)
                                    payload = event.get("payload") or {}
                                    kind = event.get("type")
                                    if kind == "session_meta":
                                        state["thread"] = payload.get("id", state["thread"])
                                        state["project"] = project_name(payload.get("cwd", ""))
                                        if payload.get("timestamp"):
                                            state["created"] = timestamp(payload["timestamp"])
                                    elif kind == "turn_context":
                                        state["model"] = payload.get("model") or "unknown"
                                        state["effort"] = reasoning_effort(payload)
                                    elif kind == "event_msg" and payload.get("type") == "token_count":
                                        info = payload.get("info") or {}
                                        total = info.get("total_token_usage")
                                        if not isinstance(total, dict):
                                            continue
                                        values = delta(total, state["previous"], info.get("last_token_usage"))
                                        state["previous"] = total
                                        when = timestamp(event["timestamp"])
                                        if when < cutoff or not values["total"]:
                                            continue
                                        digest = hashlib.sha256(json.dumps([when, info], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                                        self.db.execute("""
                                          INSERT INTO events(fingerprint,ts,thread,model,project,input,cached,
                                                             output,reasoning,total,source_created,effort)
                                          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                                          ON CONFLICT(fingerprint) DO UPDATE SET
                                            thread=excluded.thread,model=excluded.model,project=excluded.project,
                                            effort=excluded.effort,
                                            input=excluded.input,cached=excluded.cached,output=excluded.output,
                                            reasoning=excluded.reasoning,total=excluded.total,
                                            source_created=excluded.source_created
                                          WHERE excluded.source_created < events.source_created
                                        """, (digest, when, state["thread"], state["model"], state["project"],
                                              *(values[key] for key in FIELDS), state["created"], state["effort"]))
                                        if backfill:
                                            # Enrich an existing event without changing its original counts
                                            # or letting copied fork history replace the original owner.
                                            self.db.execute("""UPDATE events SET effort=?
                                                WHERE fingerprint=? AND thread=? AND source_created=?""",
                                                (state["effort"], digest, state["thread"], state["created"]))
                                        inserted += 1
                                except (ValueError, TypeError, KeyError, AttributeError):
                                    warnings.append("跳过不支持的计数记录：" + path.name)
                        self.db.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?)",
                                        (str(path), stat.st_size, stat.st_mtime_ns, json.dumps(state)))
                    except OSError:
                        warnings.append("日志暂时无法读取：" + path.name)
                if not history:
                    self.db.execute("DELETE FROM events WHERE ts<?", (cutoff,))
                else:
                    self.db.execute("INSERT OR REPLACE INTO meta VALUES('history_enabled','1')")
                self.db.execute("INSERT OR REPLACE INTO meta VALUES('initialized','1')")
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise
            first = not self.initialized
            self.initialized = True
            self.history_enabled = history
            self.last_scan = now
            self.last_result = dict(scannedAt=now * 1000, initial=first, filesChanged=changed,
                                    bytesRead=read_bytes, seconds=round(time.monotonic() - started, 3),
                                    warnings=sorted(set(warnings))[:20])
            return self.last_result

    def accounts(self):
        with self.lock:
            return dict(revision=self.db.execute("SELECT value FROM attribution.settings WHERE key='revision'").fetchone()[0],
                        marks=[dict(start=row[0], account=row[1]) for row in
                               self.db.execute("SELECT start,account FROM attribution.marks ORDER BY start")])

    def save_accounts(self, data, now=None):
        now = time.time() if now is None else now
        if not isinstance(data, dict) or type(data.get("revision")) is not int:
            raise ValueError("账号时段版本无效，请重新打开管理窗口")
        rows = data.get("marks")
        if not isinstance(rows, list) or len(rows) > 2000:
            raise ValueError("账号切换记录最多 2000 条")
        validated, seen = [], set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("账号切换记录格式无效")
            start, account = row.get("start"), row.get("account")
            if type(start) not in (int, float) or not math.isfinite(start) or start != int(start) or not 0 <= start <= (now + 60) * 1000:
                raise ValueError("请选择有效的开始时间，且不能晚于当前时间")
            if not isinstance(account, str) or not account.strip() or len(account.strip()) > 80:
                raise ValueError("账号名称须为 1–80 个字符")
            account = account.strip()
            if account == "未知账号" or any(ord(char) < 32 for char in account):
                raise ValueError("请选择有效的账号名称；未知账号请使用专门选项")
            if start in seen:
                raise ValueError("同一个时间只能标记一个账号，请先修改原记录")
            seen.add(start)
            validated.append((int(start), account))
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            revision = self.db.execute("SELECT value FROM attribution.settings WHERE key='revision'").fetchone()[0]
            if data["revision"] != revision:
                raise AccountConflict("账号时段已被另一页面修改，请关闭后重新打开，再进行修改")
            self.db.execute("DELETE FROM attribution.marks")
            self.db.executemany("INSERT INTO attribution.marks VALUES(?,?)", sorted(validated))
            self.db.execute("UPDATE attribution.settings SET value=value+1 WHERE key='revision'")
            result = self.accounts()
        return result

    def task_names(self, ids):
        names = {ident: "会话 · " + ident[:8] for ident in ids}
        internal = set()
        databases = sorted(self.root.glob("state_*.sqlite"),
                           key=lambda p: int(re.search(r"state_(\d+)", p.name).group(1))
                           if re.search(r"state_(\d+)", p.name) else 0, reverse=True)
        for path in databases:
            conn = None
            try:
                conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
                columns = {row[1] for row in conn.execute("PRAGMA table_info(threads)")}
                if "id" not in columns:
                    continue
                display = "name" if "name" in columns else "NULL"
                prefix = "substr(title,1,100)" if "title" in columns else "NULL"
                for ident in ids:
                    row = conn.execute("SELECT " + display + "," + prefix + " FROM threads WHERE id=?", (ident,)).fetchone()
                    if not row:
                        continue
                    if (row[1] or "").startswith("The following is the Codex agent history"):
                        names[ident] = "内部审批检查 · " + ident[:8]
                        internal.add(ident)
                    elif row[0]:
                        names[ident] = str(row[0])[:160]
                break
            except sqlite3.Error:
                continue
            finally:
                if conn:
                    conn.close()
        return names, internal

    def quota_history(self, cutoff, now):
        folder = self.config.get("quota_dir")
        if not folder:
            return [], []
        source = Path(folder) / "quota-history.jsonl"
        if not source.exists():
            return [], []
        points, issues, groups = [], [], {}
        try:
            with source.open("r", encoding="utf-8-sig") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                        when = timestamp(row["captured_at_utc"])
                        if when < cutoff or when > now:
                            continue
                        account = row.get("account_id", "")
                        groups.setdefault(account, len(groups))
                        windows = []
                        for w in row.get("windows", []):
                            minutes = w.get("window_minutes")
                            duration = (str(minutes // 1440) + " 天") if minutes and minutes % 1440 == 0 else (str(minutes // 60) + " 小时" if minutes and minutes % 60 == 0 else str(minutes) + " 分钟")
                            label = "Codex" if w["limit_id"] == "codex" else w.get("limit_name") or w["limit_id"]
                            windows.append(dict(key=w["limit_id"] + ":" + w["window"], name=label + " · " + duration,
                                                remaining=w.get("remaining_percent"), reset=w.get("resets_at")))
                        points.append(dict(t=when * 1000, windows=windows, account=groups[account],
                                           credits=row.get("available_reset_credits")))
                    except (ValueError, KeyError, TypeError):
                        issues.append("有未完成或无效的额度记录，已跳过")
        except OSError:
            issues.append("暂时无法读取额度历史文件")
        return sorted({p["t"]: p for p in points}.values(), key=lambda p: p["t"]), sorted(set(issues))

    def view(self, hours, now, names, internal, start=None, inclusive_end=True):
        start = now - hours * 3600 if start is None else start
        end_operator = "<=" if inclusive_end else "<"
        shift = self.config["timezone_offset"] * 60
        query = """
          WITH selected AS (
            SELECT *, (ts+?)/3600.0 AS local_hour,
                   COALESCE((SELECT account FROM attribution.marks WHERE start<=events.ts*1000
                             ORDER BY start DESC LIMIT 1), '__unknown__') AS account
            FROM events WHERE ts>=? AND ts{end_operator}?
          )
          SELECT (CAST(local_hour AS INTEGER) - (local_hour < CAST(local_hour AS INTEGER)))*3600-?
                 AS bucket,thread,model,effort,project,
                 SUM(input),SUM(cached),SUM(output),SUM(reasoning),SUM(total),account
          FROM selected GROUP BY bucket,thread,model,effort,project,account
          ORDER BY bucket,thread,model,effort
        """
        buckets = {}
        for row in self.db.execute(query.format(end_operator=end_operator), (shift, start, now, shift)):
            task = dict(id=row[1], title=names.get(row[1], "会话 · " + row[1][:8]), model=row[2],
                        effort=row[3], project=row[4], internal=row[1] in internal or row[2] == "codex-auto-review",
                        account=row[10], **dict(zip(FIELDS, row[5:10])))
            buckets.setdefault(row[0], []).append(task)
        earliest, latest = self.db.execute("SELECT MIN(ts),MAX(ts) FROM events WHERE ts>=? AND ts" + end_operator + "?", (start, now)).fetchone()
        result = []
        bucket = math.floor((start + shift) / 3600) * 3600 - shift
        while bucket < now:
            result.append(dict(id=int(bucket), start=max(bucket, start) * 1000,
                               end=min(bucket + 3600, now) * 1000, tasks=buckets.get(bucket, [])))
            bucket += 3600
        return dict(hours=hours, start=start * 1000, end=now * 1000, intervals=result,
                    firstEvent=earliest * 1000 if earliest is not None else None,
                    lastEvent=latest * 1000 if latest is not None else None)

    def snapshot(self, force=False, now=None, start=None, end=None):
        now = time.time() if now is None else now
        selected = custom_range(start, end, now)
        with self.lock:
            scan = self.refresh(force, now, full_history=selected is not None)
            coverage_start = min(now - 7 * 86400, selected[0]) if selected else now - 7 * 86400
            coverage_end = max(now, selected[1]) if selected else now
            id_query = "SELECT DISTINCT thread FROM events WHERE (ts>=? AND ts<=?)"
            id_params = (now - 7 * 86400, now)
            if selected:
                id_query += " OR (ts>=? AND ts<?)"
                id_params += selected
            ids = {row[0] for row in self.db.execute(id_query, id_params)}
            names, internal = self.task_names(ids)
            quota, warnings = self.quota_history(coverage_start, coverage_end)
            if selected:
                quota = [point for point in quota
                         if now - 7 * 86400 <= point["t"] / 1000 <= now
                         or selected[0] <= point["t"] / 1000 < selected[1]]
            views = {str(hours): self.view(hours, now, names, internal) for hours in (24, 168)}
            if selected:
                range_start, range_end = selected
                views["custom"] = self.view((range_end - range_start) / 3600, range_end, names, internal,
                                            start=range_start, inclusive_end=False)
            return dict(version=1, generatedAt=now * 1000, machine=platform.node(),
                        timezone=self.config["timezone"], timezoneOffset=self.config["timezone_offset"],
                        refreshSeconds=self.config["refresh_seconds"], monitorId=self.config.get("monitor_thread_id", ""),
                        views=views, quota=quota, accounts=self.accounts(), scan=scan, warnings=scan["warnings"] + warnings)
