"""Shared configuration; relative paths are based on the repository root."""
import json, os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / 'config/config.json'
def load(path=DEFAULT_CONFIG):
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((ROOT/'config/config.example.json').read_text(encoding='utf-8-sig'), encoding='utf-8')
    return json.loads(path.read_text(encoding='utf-8-sig'))
def resolve(value):
    p = Path(os.path.expandvars(str(value))).expanduser()
    return p.resolve() if p.is_absolute() else (ROOT/p).resolve()
def codex_root(config):
    return resolve(config.get('codex_root') or os.environ.get('CODEX_HOME') or Path.home()/'.codex')
