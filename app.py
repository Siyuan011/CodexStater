#!/usr/bin/env python3
"""Codex Stater: local-only dynamic dashboard, Python 3.9+."""
import argparse
import hashlib
import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from usage_store import UsageStore

BASE = Path(__file__).resolve().parent
APP_ID = "codex-local-stater-v1"
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def load_config(path, args):
    path = path.expanduser().resolve()
    config = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    parent = path.parent
    def resolve(value):
        p = Path(os.path.expandvars(value)).expanduser()
        return str((parent / p).resolve()) if not p.is_absolute() else str(p.resolve())
    config["codex_root"] = resolve(str(args.codex_root or config.get("codex_root") or os.environ.get("CODEX_HOME") or Path.home() / ".codex"))
    quota = args.quota_dir if args.quota_dir is not None else config.get("quota_dir")
    config["quota_dir"] = resolve(str(quota)) if quota else None
    config["cache_dir"] = resolve(config.get("cache_dir") or ".cache")
    config["port"] = args.port or int(config.get("port", 8766))
    config["refresh_seconds"] = int(config.get("refresh_seconds", 60))
    config["timezone"] = config.get("timezone", "+08:00")
    match = re.fullmatch(r"([+-])(\d\d):(\d\d)", config["timezone"])
    if not match or int(match[2]) > 14 or int(match[3]) > 59 or (int(match[2]) == 14 and int(match[3])):
        raise ValueError("timezone 应为 -14:00 至 +14:00 的固定偏移")
    config["timezone_offset"] = (1 if match[1] == "+" else -1) * (int(match[2]) * 60 + int(match[3]))
    if not 1024 <= config["port"] <= 65535:
        raise ValueError("端口应在 1024–65535 之间")
    if not 5 <= config["refresh_seconds"] <= 86400:
        raise ValueError("刷新间隔应在 5–86400 秒之间")
    config["config_path"] = str(path)
    signature = {key: config.get(key) for key in ("codex_root", "quota_dir", "cache_dir", "refresh_seconds", "timezone", "monitor_thread_id")}
    config["signature"] = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
    return config


def page(data=None):
    template = (BASE / "web/index.html").read_text(encoding="utf-8")
    css = (BASE / "web/dashboard.css").read_text(encoding="utf-8")
    js = "\n".join((BASE / name).read_text(encoding="utf-8") for name in ("web/logic.js", "web/share-chart.js", "web/dashboard.js"))
    packed = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return template.replace("/*__STYLE__*/", css).replace("/*__SCRIPT__*/", js).replace("__BOOTSTRAP__", packed)


def health(config):
    try:
        with HTTP.open("http://127.0.0.1:%d/health" % config["port"], timeout=1) as response:
            result = json.load(response)
        if result.get("app") != APP_ID or result.get("signature") != config["signature"]:
            raise RuntimeError("端口已被其他服务或另一份配置占用，请在 config.json 中改用其他端口")
        return result
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return None


def serve(config):
    store = UsageStore(config)
    shutdown_key = secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def allowed(self):
            valid = {"127.0.0.1:%d" % config["port"], "localhost:%d" % config["port"]}
            if self.headers.get("Host") not in valid:
                return False
            origin = self.headers.get("Origin")
            return not origin or origin in {"http://" + host for host in valid}

        def send(self, status, body, content_type):
            payload = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'none'")
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def data(self, status, body):
            self.send(status, json.dumps(body, ensure_ascii=False), "application/json; charset=utf-8")

        def do_GET(self):
            if not self.allowed():
                return self.data(403, {"error": "只允许本机同源访问"})
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/":
                return self.send(200, page(), "text/html; charset=utf-8")
            if parsed.path == "/health":
                return self.data(200, dict(app=APP_ID, signature=config["signature"], pid=os.getpid()))
            if parsed.path == "/api/data":
                try:
                    query = urllib.parse.parse_qs(parsed.query)
                    return self.data(200, store.snapshot(force=query.get("force") == ["1"]))
                except Exception as error:
                    print("数据刷新失败：" + str(error), file=sys.stderr, flush=True)
                    return self.data(500, {"error": "刷新失败：" + str(error)})
            if parsed.path == "/favicon.ico":
                return self.send(204, b"", "image/x-icon")
            return self.data(404, {"error": "not found"})

        def do_POST(self):
            if not self.allowed() or self.path != "/api/shutdown" or self.headers.get("X-Stater-Key") != shutdown_key:
                return self.data(403, {"error": "forbidden"})
            self.data(200, {"status": "stopping"})
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    server = ThreadingHTTPServer(("127.0.0.1", config["port"]), Handler)
    server.daemon_threads = True
    runtime = Path(config["cache_dir"]) / ("server-%d.json" % config["port"])
    runtime.write_text(json.dumps(dict(pid=os.getpid(), key=shutdown_key, signature=config["signature"])), encoding="utf-8")
    print("http://127.0.0.1:%d" % config["port"], flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        store.close()
        if runtime.exists():
            try:
                if json.loads(runtime.read_text(encoding="utf-8"))["pid"] == os.getpid():
                    runtime.unlink()
            except (OSError, ValueError, KeyError):
                pass


def launch(config, args):
    running = health(config)
    if not running:
        Path(config["cache_dir"]).mkdir(parents=True, exist_ok=True)
        command = [sys.executable, str(BASE / "app.py"), "serve", "--config", config["config_path"],
                   "--codex-root", config["codex_root"], "--port", str(config["port"])]
        if config["quota_dir"]:
            command.extend(["--quota-dir", config["quota_dir"]])
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
        with (Path(config["cache_dir"]) / "server.log").open("a", encoding="utf-8") as log:
            child = subprocess.Popen(command, cwd=BASE, stdout=log, stderr=log, **options)
        for _ in range(50):
            if child.poll() is not None:
                raise RuntimeError("服务启动失败，请查看 .cache/server.log")
            time.sleep(0.2)
            running = health(config)
            if running:
                break
        if not running:
            raise RuntimeError("启动超时，请查看 .cache/server.log")
    url = "http://127.0.0.1:%d" % config["port"]
    if not args.no_browser:
        webbrowser.open(url)
    print(json.dumps(dict(status="running", url=url, pid=running["pid"]), ensure_ascii=False))


def stop(config):
    if not health(config):
        print("服务未运行")
        return
    runtime = Path(config["cache_dir"]) / ("server-%d.json" % config["port"])
    data = json.loads(runtime.read_text(encoding="utf-8"))
    request = urllib.request.Request("http://127.0.0.1:%d/api/shutdown" % config["port"], data=b"",
                                     headers={"X-Stater-Key": data["key"]}, method="POST")
    with HTTP.open(request, timeout=3) as response:
        print(response.read().decode("utf-8"))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Codex 本机实时用量面板")
    parser.add_argument("command", nargs="?", choices=["launch", "serve", "export", "stop"], default="launch")
    parser.add_argument("--config", type=Path, default=BASE / "config.json")
    parser.add_argument("--codex-root", type=Path)
    parser.add_argument("--quota-dir", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--output", type=Path, default=BASE / "最新用量报告.html")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        config = load_config(args.config, args)
        if args.command == "serve":
            serve(config)
        elif args.command == "launch":
            launch(config, args)
        elif args.command == "stop":
            stop(config)
        else:
            store = UsageStore(config)
            try:
                report = page(store.snapshot(force=True))
                output = args.output.expanduser().resolve()
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(report, encoding="utf-8")
                print(json.dumps(dict(status="ok", html=str(output)), ensure_ascii=False))
            finally:
                store.close()
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    import sqlite3
    raise SystemExit(main())
