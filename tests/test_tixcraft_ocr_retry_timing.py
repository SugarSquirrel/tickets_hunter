"""Offline retry instrumentation equivalence; synthetic answers only, no browser I/O."""
import ast
import asyncio
import contextlib
import io
import time
import types
import unittest
from unittest.mock import patch

from test_flow_timing import ROOT, StripTimings, flow_stage


def run_retry(answers, *, enabled=True, instrumented=True, hash_matches=True,
              candidate=False, changed_url=False, logger_failure=False):
    tree = ast.parse((ROOT / 'src/platforms/tixcraft.py').read_text(encoding='utf-8'))
    names = {'nodriver_tixcraft_auto_ocr', 'nodriver_tixcraft_ticket_main_ocr',
             'nodriver_tixcraft_reload_captcha'}
    tree.body = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name in names]
    if not instrumented:
        tree = StripTimings().visit(tree)
    calls, pending = [], iter(answers)
    debug = types.SimpleNamespace(log=lambda *args: None)

    class Tab:
        async def query_selector(self, selector):
            calls.append(('query', selector))
            return object()

        async def evaluate(self, script, **kwargs):
            calls.append(('refresh', script, kwargs))
            return True

        async def send(self, event):
            calls.append(('send', event))

    async def classify(*args, **kwargs):
        calls.append(('classify',))
        return next(pending)

    async def hash_read(tab):
        calls.append(('hash_read',))
        return 1

    def verify(answer, value):
        calls.append(('hash_validate',))
        return hash_matches or answer == 'GOOD'

    def edit(answer, value):
        calls.append(('hash_edit',))
        return ['GOOD'] if candidate else []

    async def keyin(tab, **kwargs):
        calls.append(('keyin', kwargs.get('answer'), kwargs.get('auto_submit', False)))
        return False, bool(kwargs.get('auto_submit', False))

    async def pause(config):
        return False

    async def sleep(delay):
        calls.append(('sleep', delay))

    async def url(tab):
        calls.append(('url',))
        return ('private-changed' if changed_url and calls.count(('url',)) > 1 else 'private-url'), False

    ns = dict(flow_stage=flow_stage, time=time, _state={},
              asyncio=types.SimpleNamespace(sleep=sleep),
              util=types.SimpleNamespace(create_debug_logger=lambda *args, **kwargs: debug,
                                         yii_captcha_verify=verify, yii_captcha_edit1=edit),
              cdp=types.SimpleNamespace(page=types.SimpleNamespace(
                  handle_java_script_dialog=lambda **kwargs: ('dismiss', kwargs))),
              check_and_handle_pause=pause, nodriver_current_url=url,
              nodriver_tixcraft_get_ocr_answer=classify,
              nodriver_get_yii_captcha_hash=hash_read,
              nodriver_tixcraft_keyin_captcha_code=keyin,
              CONST_OCR_CAPTCH_IMAGE_SOURCE_CANVAS='canvas')
    exec(compile(ast.fix_missing_locations(tree), '<isolated retry>', 'exec'), ns)
    config = {'advanced': {'show_timing_log': enabled, 'ocr_retry_cooldown': 0.7,
                           'post_failure_lockdown_seconds': 0},
              'ocr_captcha': {'enable': True, 'force_submit': True, 'image_source': 'canvas'}}
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        if logger_failure:
            with patch('builtins.print', side_effect=OSError('private logger failure')):
                result = asyncio.run(ns['nodriver_tixcraft_ticket_main_ocr'](Tab(), config, object(), None, 'unit'))
        else:
            result = asyncio.run(ns['nodriver_tixcraft_ticket_main_ocr'](Tab(), config, object(), None, 'unit'))
    # Exclude the wall clock recorded after the unchanged successful submit path.
    state = {key: value for key, value in ns['_state'].items() if key != 'form_submitted_at'}
    return (result, state), calls, output.getvalue()


class RetryTimingTests(unittest.TestCase):
    def assert_equivalent(self, answers, **options):
        result, calls, logs = run_retry(answers, **options)
        for variant in ({'enabled': False}, {'instrumented': False}, {'logger_failure': True}):
            other_result, other_calls, other_logs = run_retry(answers, **options, **variant)
            self.assertEqual((other_result, other_calls), (result, calls))
            self.assertEqual(other_logs, '')
        self.assertNotIn('GOOD', logs)
        self.assertNotIn('private-', logs)
        self.assertNotIn('yiiCaptcha', logs)
        return result, calls, logs

    def test_invalid_length_refresh_wait_then_one_submit(self):
        result, calls, logs = self.assert_equivalent(['BAD', 'GOOD'])
        self.assertEqual([c for c in calls if c[0] == 'sleep'], [('sleep', 0.3)])
        self.assertEqual(len([c for c in calls if c[0] == 'refresh']), 1)
        self.assertEqual([c for c in calls if c[0] == 'keyin'], [('keyin', 'GOOD', True)])
        self.assertRegex(logs, r'stage=ocr_retry_reason .*outcome=invalid_length_changed')
        self.assertRegex(logs, r'stage=ocr_retry_refresh .*outcome=invalid_length')
        self.assertRegex(logs, r'stage=ocr_retry_wait .*outcome=canvas_refresh')
        self.assertRegex(logs, r'stage=ocr_retry_url_check .*outcome=same_page')
        self.assertEqual(result[1], {'ocr_completed_url': 'private-url'})

    def test_missing_answer_keeps_existing_short_wait(self):
        _, calls, logs = self.assert_equivalent([None, 'GOOD'])
        self.assertEqual([c for c in calls if c[0] == 'sleep'], [('sleep', 0.1)])
        self.assertFalse(any(c[0] == 'refresh' for c in calls))
        self.assertRegex(logs, r'stage=ocr_retry_reason .*outcome=missing_answer')

    def test_same_invalid_answer_keeps_refresh_suppression_and_cooldown(self):
        _, calls, logs = self.assert_equivalent(['BAD', 'BAD', 'BAD', 'GOOD'])
        self.assertEqual(len([c for c in calls if c[0] == 'refresh']), 1)
        self.assertEqual([c for c in calls if c[0] == 'sleep'], [('sleep', 0.3), ('sleep', 0.7)])
        self.assertEqual(len([c for c in calls if c[0] == 'send']), 1)
        self.assertEqual(len([c for c in calls if c[0] == 'keyin']), 1)
        self.assertEqual(logs.count('outcome=invalid_length_same'), 2)
        self.assertIn('stage=ocr_retry_alert_dismiss', logs)
        self.assertRegex(logs, r'stage=ocr_retry_wait .*outcome=cooldown')

    def test_hash_mismatch_refresh_has_no_new_sleep_or_submit(self):
        _, calls, logs = self.assert_equivalent(['FAIL', 'GOOD'], hash_matches=False)
        self.assertFalse(any(c[0] == 'sleep' for c in calls))
        self.assertEqual([c for c in calls if c[0] == 'keyin'], [('keyin', 'GOOD', True)])
        self.assertRegex(logs, r'stage=ocr_hash_validate .*outcome=mismatch')
        self.assertRegex(logs, r'stage=ocr_hash_edit .*outcome=no_candidate')
        self.assertRegex(logs, r'stage=ocr_retry_reason .*outcome=hash_mismatch')
        self.assertRegex(logs, r'stage=ocr_retry_refresh .*outcome=hash_mismatch')

    def test_hash_candidate_does_not_retry(self):
        _, calls, logs = self.assert_equivalent(['FAIL'], hash_matches=False, candidate=True)
        self.assertFalse(any(c[0] in ('refresh', 'sleep') for c in calls))
        self.assertEqual([c for c in calls if c[0] == 'keyin'], [('keyin', 'GOOD', True)])
        self.assertNotIn('stage=ocr_retry_reason', logs)
        self.assertRegex(logs, r'stage=ocr_hash_edit .*outcome=candidate')

    def test_changed_page_stops_retry_without_submit(self):
        result, calls, logs = self.assert_equivalent([None], changed_url=True)
        self.assertEqual(result[1], {})
        self.assertFalse(any(c[0] == 'keyin' for c in calls))
        self.assertRegex(logs, r'stage=ocr_retry_url_check .*outcome=changed_page')

    def test_fifth_failure_still_falls_back_once_without_auto_submit(self):
        result, calls, logs = run_retry([None] * 5)
        disabled_result, disabled_calls, disabled_logs = run_retry([None] * 5, enabled=False)
        self.assertEqual((result, calls), (disabled_result, disabled_calls))
        self.assertEqual([c for c in calls if c[0] == 'keyin'], [('keyin', None, False)])
        self.assertEqual(logs.count('stage=ocr_retry_reason'), 5)
        self.assertNotIn('[STAGE]', disabled_logs)


if __name__ == '__main__':
    unittest.main()
