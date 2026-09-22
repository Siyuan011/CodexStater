"""Incremental, metadata-only Codex usage sampling. Standard library only."""
import argparse
import hashlib
import json
import os
import platform
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

FIELDS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
          "output_tokens", "reasoning_output_tokens", "total_tokens")
TZ = timezone(timedelta(hours=8))


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def usage_delta(current, previous, last):
    if previous is None or any(current.get(k, 0) < previous.get(k, 0)
                               for k in ("input_tokens", "output_tokens", "total_tokens")):
        # A fresh stream may inherit history; never count its inherited total.
        return {k: max(0, int((last or {}).get(k, 0))) for k in FIELDS}
    return {k: max(0, int(current.get(k, 0)) - int(previous.get(k, 0))) for k in FIELDS}


def seed_file(path, size):
    # Baseline uses the last 2 MiB, not a replay of the entire conversation.
    result = {"offset": 0, "thread_id": path.stem, "model": "unknown",
              "project": "", "previous": None}
    with path.open("rb") as stream:
        first = stream.readline()
        try:
            event = json.loads(first)
            meta = event.get("payload", {})
            if event.get("type") == "session_meta":
                result["thread_id"] = meta.get("id", path.stem)
                result["project"] = meta.get("cwd", "")
        except (ValueError, UnicodeError):
            pass
        start = max(0, size - 2 * 1024 * 1024)
        stream.seek(start)
        if start:
            stream.readline()
        while stream.tell() < size:
            line_start = stream.tell()
            line = stream.readline(size - line_start)
            if not line.endswith(b"\n"):
                result["offset"] = line_start
                break
            result["offset"] = stream.tell()
            if b'"turn_context"' not in line and b'"token_count"' not in line:
                continue
            try:
                event = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            payload = event.get("payload", {})
            if event.get("type") == "turn_context":
                result["model"] = payload.get("model", "unknown")
            if event.get("type") == "event_msg" and payload.get("type") == "token_count":
                info = payload.get("info") or {}
                if info.get("total_token_usage") is not None:
                    result["previous"] = info["total_token_usage"]
    return result


def export(db, out):
    history = out / "local-usage-history.jsonl"
    last_seq = 0
    if history.exists() and history.stat().st_size:
        with history.open("rb") as stream:
            stream.seek(max(0, history.stat().st_size - 8 * 1024 * 1024))
            lines = stream.read().splitlines()
        try:
            last_seq = json.loads(lines[-1])["sample_id"]
        except (ValueError, IndexError):
            # Recover a partial write from the authoritative SQLite journal.
            history.write_text("", encoding="utf-8")
    with history.open("a", encoding="utf-8") as stream:
        for seq, data in db.execute("SELECT id,data FROM samples WHERE id>? ORDER BY id", (last_seq,)):
            sample = json.loads(data)
            sample["sample_id"] = seq
            stream.write(encode(sample) + "\n")
    row = db.execute("SELECT id,data FROM samples ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return
    sample = json.loads(row[1])
    sample["sample_id"] = row[0]
    lines = ["# 本机 Codex 用量", "",
             f"机器：{sample['machine']}｜采样时间：{sample['captured_at_shanghai']}", ""]
    if sample["baseline"]:
        lines += ["已建立采集基线，从下一次采样开始统计新增 Token；未将历史累计用量计入当前小时。", ""]
    else:
        lines += [f"统计区间：{sample['since_shanghai']} 至 {sample['captured_at_shanghai']}",
                  "以下为本次新增日志中、基线建立后的用量；延迟落盘事件在发现时计入。", ""]
    lines += ["| 任务 ID | 项目 | 模型 | 输入 | 缓存输入（含于输入） | 输出 | 合计 |",
              "| --- | --- | --- | ---: | ---: | ---: | ---: |"]
    for item in sorted(sample["tasks"], key=lambda x: x["total_tokens"], reverse=True):
        project = Path(item["project"]).name.replace("|", "/")
        lines.append(f"| {item['thread_id']} | {project} | {item['model']} | "
                     f"{item['input_tokens']:,} | {item['cached_input_tokens']:,} | "
                     f"{item['output_tokens']:,} | {item['total_tokens']:,} |")
    lines += ["", f"本次合计：{sample['totals']['total_tokens']:,} Token。",
              "", "缓存输入已包含在输入中，推理输出已包含在输出中，不重复相加。",
              "仅代表本机 Codex 日志中可见的用量，不换算订阅额度百分比，不作进程归因。",
              "日志不含可靠的逐事件账号标识；切换账号、迁移或复制日志时，不能把这些数据当作当前账号的完整账单。",
              "未发现于本机日志的云端、其他机器或其他客户端用量不在统计范围。",
              "程序只提取计数、时间、任务、模型和项目元数据，不保存对话正文。"]
    if sample["warnings"]:
        lines += ["", "采集提示：" + "；".join(sample["warnings"])]
    temp = out / "本机用量.md.tmp"
    temp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(temp, out / "本机用量.md")


def collect(root, out, state_dir=None):
    out.mkdir(parents=True, exist_ok=True)
    if not (root / "sessions").is_dir():
        raise RuntimeError("Codex sessions directory unavailable")
    state_dir = Path(state_dir or out)
    state_dir.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(state_dir / "local-usage-state.sqlite", timeout=10)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, mtime INTEGER, size INTEGER, state TEXT);
        CREATE TABLE IF NOT EXISTS seen(key TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS samples(id INTEGER PRIMARY KEY, data TEXT);
    """)
    # Recover exports from a previously committed sample before reading more logs.
    export(db, out)
    now = utcnow()
    latest = db.execute("SELECT data FROM samples ORDER BY id DESC LIMIT 1").fetchone()
    initial = latest is None
    previous_sample = json.loads(latest[0]) if latest else None
    baseline_at = previous_sample["baseline_at"] if latest else now
    groups = defaultdict(lambda: {k: 0 for k in FIELDS})
    warnings = []
    read_bytes = 0
    changed_files = 0
    candidates = []
    for folder in ("sessions", "archived_sessions"):
        directory = root / folder
        if directory.is_dir():
            candidates.extend(directory.rglob("*.jsonl"))
    db.execute("BEGIN IMMEDIATE")
    try:
        for path in candidates:
            try:
                stat = path.stat()
                old = db.execute("SELECT mtime,size,state FROM files WHERE path=?", (str(path),)).fetchone()
                if old and old[0] == stat.st_mtime_ns and old[1] == stat.st_size:
                    continue
                changed_files += 1
                if initial:
                    state = seed_file(path, stat.st_size)
                    read_bytes += min(stat.st_size, 2 * 1024 * 1024)
                else:
                    state = json.loads(old[2]) if old else {
                        "offset": 0, "thread_id": path.stem, "model": "unknown",
                        "project": "", "previous": None}
                    if old and (stat.st_size < state["offset"] or
                                (stat.st_size == old[1] and stat.st_mtime_ns != old[0])):
                        state = {"offset": 0, "thread_id": path.stem, "model": "unknown",
                                 "project": "", "previous": None}
                        warnings.append("日志发生截断或替换，已重新扫描并按事件去重")
                    with path.open("rb") as stream:
                        stream.seek(state["offset"])
                        while stream.tell() < stat.st_size:
                            start = stream.tell()
                            line = stream.readline(stat.st_size - start)
                            read_bytes += len(line)
                            if not line.endswith(b"\n"):
                                break
                            state["offset"] = stream.tell()
                            if not any(x in line for x in (b'"session_meta"', b'"turn_context"', b'"token_count"')):
                                continue
                            try:
                                event = json.loads(line)
                            except (ValueError, UnicodeError):
                                warnings.append("跳过一条无效日志记录")
                                continue
                            payload = event.get("payload", {})
                            kind = event.get("type")
                            if kind == "session_meta":
                                state["thread_id"] = payload.get("id", path.stem)
                                state["project"] = payload.get("cwd", "")
                            elif kind == "turn_context":
                                state["model"] = payload.get("model", "unknown")
                            elif kind == "event_msg" and payload.get("type") == "token_count":
                                info = payload.get("info") or {}
                                total = info.get("total_token_usage")
                                if total is None:
                                    continue
                                delta = usage_delta(total, state["previous"], info.get("last_token_usage"))
                                state["previous"] = total
                                stamp = event.get("timestamp")
                                if not stamp or parse_time(stamp) <= parse_time(baseline_at):
                                    continue
                                # Exclude thread ID: forked/copied history preserves timestamps and usage.
                                identity = encode([stamp, info])
                                fingerprint = hashlib.sha256(identity.encode()).hexdigest()
                                inserted = db.execute("INSERT OR IGNORE INTO seen VALUES(?)", (fingerprint,)).rowcount
                                if inserted and delta["total_tokens"]:
                                    key = (state["thread_id"], state["model"], state["project"])
                                    for field in FIELDS:
                                        groups[key][field] += delta[field]
                db.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?)",
                           (str(path), stat.st_mtime_ns, stat.st_size, encode(state)))
            except (OSError, ValueError) as error:
                warnings.append(f"{path.name}: {type(error).__name__}")
        tasks = [dict(thread_id=k[0], model=k[1], project=k[2], **v) for k, v in groups.items()]
        sample = {
            "baseline": initial, "baseline_at": baseline_at,
            "captured_at_utc": now,
            "captured_at_shanghai": parse_time(now).astimezone(TZ).isoformat(),
            "since_utc": previous_sample["captured_at_utc"] if latest else now,
            "since_shanghai": previous_sample["captured_at_shanghai"] if latest else parse_time(now).astimezone(TZ).isoformat(),
            "machine": platform.node(), "scope": "local_log_events_not_account_billing",
            "tasks": tasks,
            "totals": {k: sum(v[k] for v in tasks) for k in FIELDS},
            "warnings": sorted(set(warnings)), "files_changed": changed_files,
            "bytes_read": read_bytes,
        }
        db.execute("INSERT INTO samples(data) VALUES(?)", (encode(sample),))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    export(db, out)
    db.close()
    print(encode({"status": "warning" if warnings else "ok", "baseline": initial,
                  "tasks": len(tasks), "new_tokens": sample["totals"]["total_tokens"],
                  "files_changed": changed_files, "bytes_read": read_bytes,
                  "warnings": len(set(warnings))}))
    return sample


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex-root", type=Path, default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))))
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    collect(args.codex_root, args.output)
