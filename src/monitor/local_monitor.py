"""Hourly local sampling: account metadata RPC only, never a model turn."""
import argparse
import sys
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from settings import ROOT as PROJECT, DEFAULT_CONFIG, load, resolve, codex_root
ROOT = PROJECT / 'data'
LOGS = PROJECT / 'logs'
CACHE = PROJECT / 'cache/monitor'
HIDDEN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

def now():
    return datetime.now(timezone.utc).isoformat()

def append(name, value):
    with ((LOGS if name in ('quota-errors.jsonl', 'local-monitor-history.jsonl') else ROOT) / name).open('a', encoding='utf-8') as f:
        f.write(json.dumps(value, ensure_ascii=False) + '\n')

def quota(codex_root, executable=None):
    exe = executable or shutil.which('codex.exe')
    if not exe:
        candidates = list((Path(os.environ['LOCALAPPDATA']) / 'OpenAI/Codex/bin').glob('*/codex.exe'))
        if candidates:
            exe = str(max(candidates, key=lambda p: p.stat().st_mtime))
    if not exe:
        raise RuntimeError('Codex executable not found')
    env = dict(os.environ, CODEX_HOME=str(codex_root))
    proc = subprocess.Popen([exe, 'app-server', '--stdio'], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, encoding='utf-8', env=env, creationflags=HIDDEN)
    messages = queue.Queue()
    def read():
        for line in proc.stdout:
            try:
                messages.put(json.loads(line))
            except ValueError:
                pass
        messages.put(None)
    threading.Thread(target=read, daemon=True).start()
    def send(value):
        proc.stdin.write(json.dumps(value) + '\n')
        proc.stdin.flush()
    def rpc(number, method, params):
        send(dict(id=number, method=method, params=params))
        import time
        deadline = time.monotonic() + 45
        while True:
            msg = messages.get(timeout=max(0.01, deadline-time.monotonic()))
            if msg is None:
                raise RuntimeError('App server exited before response')
            if msg.get('id') == number:
                if 'error' in msg:
                    raise RuntimeError(str(msg['error'])[:500])
                return msg['result']
            if time.monotonic() >= deadline:
                raise TimeoutError('Account RPC timed out')
    try:
        rpc(1, 'initialize', {'clientInfo': {'name': 'local_usage_monitor', 'version': '1.0.0'}})
        send({'method': 'initialized'})
        result = rpc(2, 'account/rateLimits/read', {})
        if not (result.get('rateLimitsByLimitId') or result.get('rateLimits')):
            raise RuntimeError('No quota buckets returned')
        return result
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

def record(data):
    captured = datetime.now(timezone.utc)
    buckets = list((data.get('rateLimitsByLimitId') or {}).values()) or [data['rateLimits']]
    rows = []
    for bucket in buckets:
        for slot in ('primary', 'secondary'):
            w = bucket.get(slot)
            if not w:
                continue
            used, reset = w.get('usedPercent'), w.get('resetsAt')
            rows.append(dict(limit_id=bucket.get('limitId'), limit_name=bucket.get('limitName'),
                window=slot, window_minutes=w.get('windowDurationMins'), used_percent=used,
                remaining_percent=None if used is None else max(0, min(100, 100-used)),
                resets_at=reset, resets_at_shanghai=None if reset is None else
                datetime.fromtimestamp(reset, timezone(timedelta(hours=8))).isoformat()))
    if not rows:
        raise RuntimeError('No quota windows returned')
    append('quota-history.jsonl', dict(captured_at_utc=captured.isoformat(),
        captured_at_shanghai=captured.astimezone(timezone(timedelta(hours=8))).isoformat(),
        account_id=data.get('accountId'), status='ok', source='local_app_server', windows=rows,
        rate_limits=buckets, available_reset_credits=(data.get('rateLimitResetCredits') or {}).get('availableCount')))
    (ROOT / 'latest-response.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    lines = ['# Codex 剩余额度', '', '采样时间：' + captured.isoformat(), '',
             '| 额度 | 窗口（分钟） | 剩余 |', '| --- | --- | --- |']
    for r in rows:
        remaining = '未知' if r['remaining_percent'] is None else str(r['remaining_percent'])+'%'
        lines.append(f"| {r['limit_name'] or r['limit_id']} | {r['window_minutes']} | {remaining} |")
    (ROOT / '最新额度.md').write_text('\n'.join(lines), encoding='utf-8')
    return len(rows)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--codex-root', type=Path)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--codex-exe')
    args = parser.parse_args()
    global ROOT, LOGS, CACHE
    config = load(args.config)
    ROOT = resolve(config.get('data_dir', 'data'))
    LOGS = resolve(config.get('logs_dir', 'logs'))
    CACHE = resolve('cache/monitor')
    for folder in (ROOT, LOGS, CACHE):
        folder.mkdir(parents=True, exist_ok=True)
    args.codex_root = args.codex_root or codex_root(config)
    # OS releases this lock even if the process crashes.
    import msvcrt
    with (CACHE / 'local-monitor.lock').open('a+b') as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return 0
        summary = {'captured_at_utc': now(), 'status': 'ok', 'quota_windows': 0}
        try:
            summary['quota_windows'] = record(quota(args.codex_root, args.codex_exe))
        except Exception as exc:
            summary['status'] = 'warning'
            summary['quota_error'] = type(exc).__name__ + ': ' + str(exc)[:500]
            append('quota-errors.jsonl', dict(captured_at_utc=now(), stage='local_quota', error=summary['quota_error']))
        try:
            spec = importlib.util.spec_from_file_location('collector', PROJECT/'src/statistics/collect_local_usage.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with contextlib.redirect_stdout(io.StringIO()):
                sample = module.collect(args.codex_root, ROOT, CACHE)
            summary['new_tokens'] = sample['totals']['total_tokens']
            summary['local_warnings'] = sample['warnings']
            if sample['warnings']:
                summary['status'] = 'warning'
        except Exception as exc:
            summary.update(status='error', local_error=type(exc).__name__ + ': ' + str(exc)[:500])
        append('local-monitor-history.jsonl', summary)
        (LOGS/'local-monitor-status.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if summary['status'] == 'ok' else 1

if __name__ == '__main__':
    raise SystemExit(main())
