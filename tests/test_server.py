import json
from datetime import datetime, timezone
import re
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

APP = Path(__file__).resolve().parents[1] / "app.py"


class ServerTest(unittest.TestCase):
    def test_local_service_reuse_export_and_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "codex/sessions").mkdir(parents=True)
            now = time.time()
            def event(seconds, kind, payload):
                return dict(timestamp=datetime.fromtimestamp(now-seconds, timezone.utc).isoformat(),
                            type=kind, payload=payload)
            medium = dict(input_tokens=100, cached_input_tokens=40, output_tokens=20,
                          reasoning_output_tokens=10, total_tokens=120)
            ultra = dict(input_tokens=300, cached_input_tokens=120, output_tokens=60,
                         reasoning_output_tokens=30, total_tokens=360)
            cumulative = {key: medium[key]+ultra[key] for key in medium}
            events = [
                event(180, "session_meta", dict(id="effort-test", timestamp=datetime.fromtimestamp(now-180, timezone.utc).isoformat())),
                event(120, "turn_context", dict(model="gpt-6-astra", effort="medium")),
                event(119, "event_msg", dict(type="token_count", info=dict(total_token_usage=medium, last_token_usage=medium))),
                event(60, "turn_context", dict(model="gpt-6-astra", effort="ultra")),
                event(59, "event_msg", dict(type="token_count", info=dict(total_token_usage=cumulative, last_token_usage=ultra))),
            ]
            (root / "codex/sessions/effort.jsonl").write_text(
                "".join(json.dumps(item)+"\n" for item in events), encoding="utf-8")
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            config = root / "config.json"
            config.write_text(json.dumps(dict(codex_root=str(root/"codex"),cache_dir=str(root/"cache"),
                                               quota_dir="",port=port,refresh_seconds=60)), encoding="utf-8")
            command = [sys.executable, str(APP), "serve", "--config", str(config)]
            flags = dict(creationflags=subprocess.CREATE_NO_WINDOW) if os.name == "nt" else {}
            child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **flags)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            base = "http://127.0.0.1:%s" % port
            try:
                for _ in range(80):
                    try:
                        with opener.open(base+"/health", timeout=.5) as response:
                            identity = json.load(response)
                        break
                    except urllib.error.URLError:
                        if child.poll() is not None:
                            self.fail(child.stderr.read().decode())
                        time.sleep(.1)
                else:
                    self.fail("server not ready")
                self.assertEqual(identity["app"],"codex-local-stater-v1")
                with opener.open(base+"/") as response:
                    html=response.read().decode("utf-8")
                self.assertIn("data-hour-overlay",html)
                self.assertRegex(html, r'<select[^>]+id="effort"')
                with opener.open(base+"/api/data") as response:
                    data=json.load(response)
                self.assertEqual(set(data["views"]),{"24","168"})
                self.assertEqual(data["warnings"],[])
                for hours in ("24", "168"):
                    rows = [task for interval in data["views"][hours]["intervals"] for task in interval["tasks"]]
                    self.assertEqual({row["effort"] for row in rows}, {"medium", "ultra"})
                    self.assertEqual(sum(row["total"] for row in rows), 480)
                    self.assertEqual(sum(row["total"] for row in rows if row["effort"] == "ultra"), 360)
                for suffix, headers in [("/../config.json",{}),("/api/data",{"Origin":"http://unrelated.example"})]:
                    with self.assertRaises(urllib.error.HTTPError) as failure:
                        opener.open(urllib.request.Request(base+suffix,headers=headers))
                    self.assertIn(failure.exception.code,(403,404))
                reused=subprocess.run([sys.executable,str(APP),"launch","--config",str(config),"--no-browser"],
                                      capture_output=True,text=True,encoding="utf-8",timeout=10)
                self.assertEqual(reused.returncode,0,reused.stderr)
                self.assertEqual(json.loads(reused.stdout)["pid"],identity["pid"])
                output=root/"snapshot.html"
                exported=subprocess.run([sys.executable,str(APP),"export","--config",str(config),"--output",str(output)],
                                        capture_output=True,text=True,encoding="utf-8",timeout=10)
                self.assertEqual(exported.returncode,0,exported.stderr)
                exported_html = output.read_text(encoding="utf-8")
                self.assertIn('"version":1', exported_html)
                packed = re.search(r'<script id="bootstrap" type="application/json">(.*?)</script>',
                                   exported_html, re.S)
                self.assertIsNotNone(packed)
                exported_data = json.loads(packed.group(1))
                exported_rows = [task for interval in exported_data["views"]["24"]["intervals"] for task in interval["tasks"]]
                self.assertEqual({row["effort"] for row in exported_rows}, {"medium", "ultra"})
                self.assertEqual(sum(row["total"] for row in exported_rows), 480)
                stopped=subprocess.run([sys.executable,str(APP),"stop","--config",str(config)],
                                       capture_output=True,text=True,encoding="utf-8",timeout=10)
                self.assertEqual(stopped.returncode,0,stopped.stderr)
                self.assertEqual(child.wait(timeout=5),0)
            finally:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=5)
                child.stdout.close()
                child.stderr.close()


if __name__=="__main__":
    unittest.main()
