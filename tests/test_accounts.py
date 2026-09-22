import json
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from usage_store import UsageStore, AccountConflict


class AccountTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'sessions').mkdir()
        self.base = int(time.time() // 3600) * 3600
        self.now = self.base + 3600
        rows = [dict(type='session_meta', payload=dict(id='same-thread')),
                dict(type='turn_context', payload=dict(model='gpt-test', effort='medium'))]
        for index in range(4):
            rows.append(dict(type='event_msg', timestamp=datetime.fromtimestamp(self.base + index * 60, timezone.utc).isoformat(),
                             payload=dict(type='token_count', info=dict(total_token_usage=dict(input_tokens=(index+1)*100, total_tokens=(index+1)*100),
                                                                       last_token_usage=dict(input_tokens=100, total_tokens=100)))))
        (self.root / 'sessions/test.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows), encoding='utf-8')
        self.config = dict(codex_root=str(self.root), cache_dir=str(self.root/'cache'), quota_dir=None,
                           timezone_offset=480, timezone='+08:00', refresh_seconds=60)
        self.store = UsageStore(self.config)
        self.addCleanup(self.store.close)

    def snapshot(self):
        return self.store.snapshot(force=True, now=self.now, start=self.base*1000, end=(self.base+240)*1000)

    def totals(self, data):
        result = {}
        for interval in data['views']['custom']['intervals']:
            for row in interval['tasks']:
                result[row['account']] = result.get(row['account'], 0) + row['total']
        return result

    def test_exact_boundaries_same_thread_same_hour_and_conservation(self):
        before = self.snapshot()
        self.assertEqual(self.totals(before), {'__unknown__':400})
        marks = [dict(start=(self.base+60)*1000, account='A'), dict(start=(self.base+120)*1000, account='B'),
                 dict(start=(self.base+180)*1000, account='__unknown__')]
        saved = self.store.save_accounts(dict(revision=0, marks=marks), now=self.now)
        self.assertEqual(saved['revision'], 1)
        after = self.snapshot()
        self.assertEqual(self.totals(after), {'__unknown__':200, 'A':100, 'B':100})
        self.assertEqual(after['scan']['bytesRead'], 0)
        self.assertEqual(sum(self.totals(after).values()), sum(self.totals(before).values()))
        self.store.save_accounts(dict(revision=1, marks=[]), now=self.now)
        self.assertEqual(self.totals(self.snapshot()), {'__unknown__':400})

    def test_persistence_outside_cache_and_open_ended_account(self):
        self.store.save_accounts(dict(revision=0, marks=[dict(start=self.base*1000, account='A')]), now=self.now)
        second = UsageStore({**self.config, 'cache_dir':str(self.root/'new-cache')})
        try:
            self.assertEqual(second.accounts()['revision'],1)
            data=second.snapshot(now=self.now, start=self.base*1000, end=(self.base+240)*1000)
            self.assertEqual(self.totals(data),{'A':400})
            with self.assertRaises(AccountConflict):
                second.save_accounts(dict(revision=0, marks=[]),now=self.now)
            self.assertEqual(second.accounts()['revision'],1)
        finally:
            second.close()

    def test_validation_is_atomic(self):
        valid=dict(start=self.base*1000,account='A')
        self.store.save_accounts(dict(revision=0,marks=[valid]),now=self.now)
        for marks in ([valid,valid], [dict(start=True,account='A')], [dict(start=float('nan'),account='A')],
                      [dict(start=-1,account='A')], [dict(start=(self.now+61)*1000,account='A')],
                      [dict(start=self.base*1000,account='')], [dict(start=self.base*1000,account='未知账号')],
                      [dict(start=self.base*1000,account='x'*81)], [dict(start=self.base*1000,account='x\ny')], None):
            with self.subTest(marks=marks), self.assertRaises(ValueError):
                self.store.save_accounts(dict(revision=1,marks=marks),now=self.now)
            self.assertEqual(self.store.accounts(),dict(revision=1,marks=[valid]))
