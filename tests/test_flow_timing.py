"""Offline Python control-flow tests. No browser, network or real CAPTCHA.

AST isolation avoids importing the browser/OCR runtime or reading user settings.
The comparison version unwraps only timing contexts, keeping application logic.
Fake evaluate results do not execute JavaScript or prove real DOM compatibility.
"""

import ast
import asyncio
import base64
import contextlib
import io
import json
import os
import re
import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from flow_timing import flow_stage, log_navigation_timing
from tixcraft_readiness import (DOCUMENT_SNAPSHOT_JS, navigate_date, read_document,
                               supported_url, ticket_document_matches, wait_ticket_select)


class StripTimings(ast.NodeTransformer):
    def visit_With(self, node):
        if isinstance(node.items[0].context_expr, ast.Call) and isinstance(node.items[0].context_expr.func, ast.Name) and node.items[0].context_expr.func.id == 'flow_stage':
            return [n for child in node.body for n in self._nodes(self.visit(child))]
        return self.generic_visit(node)

    @staticmethod
    def _nodes(node):
        return [] if node is None else node if isinstance(node, list) else [node]

    def visit_Assign(self, node):
        if any(isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == 'timing' for t in node.targets):
            return None
        return self.generic_visit(node)

    def visit_If(self, node):
        if isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Attribute) and isinstance(node.test.left.value, ast.Name) and node.test.left.value.id == 'timing':
            return None
        return self.generic_visit(node)


async def never_paused(*args):
    return False


def load_functions(instrumented=True):
    tree = ast.parse((ROOT / 'src/platforms/tixcraft.py').read_text(encoding='utf-8'))
    names = {'reset_timing', 'nodriver_tixcraft_date_auto_select', 'nodriver_tixcraft_area_auto_select',
             'nodriver_get_tixcraft_target_area', 'nodriver_tixcraft_ticket_main',
             'nodriver_tixcraft_ticket_main_agree', 'nodriver_tixcraft_assign_ticket_number',
             'nodriver_ticket_number_select_fill', 'nodriver_tixcraft_keyin_captcha_code',
             'nodriver_tixcraft_get_ocr_answer'}
    tree.body = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    if not instrumented:
        tree = StripTimings().visit(tree)
    debug = types.SimpleNamespace(enabled=False, log=lambda *args: None)
    util = types.SimpleNamespace(
        create_debug_logger=lambda *args, **kwargs: debug,
        remove_html_tags=lambda value: re.sub('<[^>]*>', '', value),
        reset_row_text_if_match_keyword_exclude=lambda config, value: False,
        get_target_item_from_matched_list=lambda rows, mode: rows[0] if rows else None,
        parse_keyword_string_to_array=lambda value: json.loads('[' + value + ']') if value else [],
        format_keyword_string=lambda value: value,
        parse_nodriver_result=lambda value: value,
        CONST_PRICE_RANGE_MAX_REMAINING='smart', CONST_SMART_SORT_REMAINING_RANK='rank',
        CONST_FROM_TOP_TO_BOTTOM='top')
    ns = dict(flow_stage=flow_stage, util=util, time=time, asyncio=asyncio, json=json, base64=base64,
              navigate_date=navigate_date, read_document=read_document,
              supported_url=supported_url,
              ticket_document_matches=ticket_document_matches, wait_ticket_select=wait_ticket_select,
              _state={}, _timing_state={'nav_start': None, 'fired': set()},
              check_and_handle_pause=never_paused, set_grabbing_critical=lambda value: None,
              get_effective_mode=lambda config: 'test', get_effective_reload_interval=lambda config: 0,
              record_area_outcome=lambda **kwargs: None, mark_bot_reload=lambda: None,
              is_reload_disabled=lambda: False, CONST_OCR_CAPTCH_IMAGE_SOURCE_CANVAS='canvas',
              CONST_OCR_CAPTCH_IMAGE_SOURCE_NON_BROWSER='non_browser',
              cdp=types.SimpleNamespace(input_=types.SimpleNamespace(dispatch_key_event=lambda kind, **kwargs: kind),
                                        page=types.SimpleNamespace(navigate=lambda url: ('navigate', url))))
    common_tree = ast.parse((ROOT / 'src/nodriver_common.py').read_text(encoding='utf-8'))
    common_tree.body = [n for n in common_tree.body if isinstance(n, ast.FunctionDef) and n.name == 'log_timing']
    exec(compile(common_tree, '<isolated log_timing>', 'exec'), ns)
    exec(compile(ast.fix_missing_locations(tree), '<isolated tixcraft>', 'exec'), ns)

    async def current_url(tab):
        return tab.url, False

    async def agree(tab, selector, *args):
        tab.calls.append(('agree', selector))
        tab.agreed = True
        return True

    async def fake_ocr_flow(tab, config, ocr, browser, domain):
        # Synthetic fixed bytes and a fixed answer, never a real CAPTCHA solver.
        answer = await ns['nodriver_tixcraft_get_ocr_answer'](tab, ocr, 'canvas', browser, domain, config)
        tab.dispatch_result = await ns['nodriver_tixcraft_keyin_captcha_code'](tab, answer, True, config)

    ns.update(nodriver_current_url=current_url, nodriver_check_checkbox_enhanced=agree,
              nodriver_tixcraft_ticket_main_ocr=fake_ocr_flow)
    return ns


def config(enabled=True):
    return {'advanced': {'show_timing_log': enabled, 'prefill_script_enable': True},
            'date_auto_select': {'enable': True, 'mode': 'top', 'date_keyword': '"wanted"'},
            'area_auto_select': {'enable': True, 'mode': 'top', 'area_keyword': '"missing","wanted"'},
            'tixcraft': {'pass_date_is_sold_out': True, 'auto_reload_coming_soon_page': False},
            'ocr_captcha': {'force_submit': True}, 'ticket_number': 2}


class FakeInput:
    def __init__(self, tab):
        self.tab = tab
        self.value = ''

    async def apply(self, js):
        self.tab.calls.append(('input_apply', js))
        if 'return element.value' in js:
            return self.value
        self.value = ''

    async def click(self):
        self.tab.calls.append(('input_click',))

    async def send_keys(self, answer):
        self.tab.calls.append(('input_keys', answer))
        self.value = answer


class FakeRow:
    def __init__(self, tab):
        self.tab = tab
        self.attrs = {'data-href': 'https://indievox.com/ticket/area/unit/1'}

    async def query_selector(self, selector):
        self.tab.calls.append(('row_query', selector))
        return self

    async def update(self):
        self.tab.calls.append(('row_update',))


class FakeTab:
    def __init__(self, *, direct_ticket=False, ready=True, fail_send=None, prefill=False, verify_prefill=True):
        self.url = 'https://indievox.com/activity/game/unit'
        self.direct_ticket, self.ready, self.fail_send = direct_ticket, ready, fail_send
        self.prefill, self.verify_prefill = prefill, verify_prefill
        self.calls = []
        self.input = FakeInput(self)
        self.quantity = '0'
        self.agreed = False
        self.dispatch_result = None

    async def wait_for(self, selector, **kwargs):
        self.calls.append(('wait', selector, kwargs))

    async def query_selector_all(self, selector):
        self.calls.append(('query_all', selector))
        return [FakeRow(self)]

    async def query_selector(self, selector):
        self.calls.append(('query', selector))
        return self.input if selector == '#TicketForm_verifyCode' else object()

    async def get(self, url):
        self.calls.append(('get', url))
        self.url = 'https://indievox.com/ticket/ticket/unit/1/1/1' if self.direct_ticket else url

    async def reload(self):
        self.calls.append(('reload',))

    async def send(self, event):
        self.calls.append(('send', event))
        if event == self.fail_send:
            raise RuntimeError('synthetic transport failure, private detail')

    async def evaluate(self, js, **kwargs):
        self.calls.append(('evaluate', js, kwargs))
        if js == DOCUMENT_SNAPSHOT_JS:
            return {'href': self.url, 'document_id': 1, 'dom_ready': True, 'select': True}
        if js == 'document.documentElement.lang':
            return 'en-US'
        if 'map(r => r.outerHTML)' in js:
            return ['<tr>wanted Find tickets</tr>']
        if "var zone = document.querySelector('.zone')" in js:
            return json.dumps([['wanted area Remaining 20', '20']])
        if "document.querySelectorAll('.zone a')" in js:
            self.url = 'https://indievox.com/ticket/ticket/unit/1/1/1'
            return None
        if js == '!!window.__TH_PREFILL_DONE__':
            return self.prefill
        if 'agree_checked:' in js:
            if self.verify_prefill:
                self.quantity, self.agreed = '2', True
            return {'ticket_set': self.verify_prefill, 'agree_checked': self.verify_prefill}
        if 'currentValue: s.value' in js:
            return json.dumps([{'id': 'TicketForm_ticketPrice_01', 'name': 'wanted', 'currentValue': self.quantity,
                                'options': [{'value': str(i), 'text': str(i), 'disabled': False} for i in range(5)]},
                               {'id': 'TicketForm_ticketPrice_02', 'name': 'wanted discount', 'currentValue': '選購一空',
                                'options': [{'value': '選購一空', 'text': '選購一空', 'disabled': True}]}])
        if 'const targetOption' in js:
            self.quantity = '2'
            return {'success': True, 'selected': '2'}
        if 'canvas.toDataURL()' in js:
            return 'data:image/png;base64,' + base64.b64encode(b'unit-only-image').decode()
        if 'element.offsetParent' in js:
            return True
        if 'return select && select.value' in js:
            return self.quantity != '0'
        if 'ready: ticketOk' in js:
            return {'ready': self.ready and self.quantity == '2' and self.agreed and self.input.value == 'UNIT',
                    'ticket': self.quantity == '2', 'agree': self.agreed, 'verify': self.input.value == 'UNIT'}
        if 'fetchPriority' in js:
            return None
        raise AssertionError('Unexpected browser call in test: ' + js[:80])


class TimingTests(unittest.TestCase):
    def test_navigation_timing_uses_browser_deltas_and_allowlisted_fields(self):
        snapshot = {'href': 'https://private/?answer=UNIT', 'navigation_timing': {
            'startTime': 0, 'requestStart': 20, 'responseStart': 120,
            'responseEnd': 150, 'domContentLoadedEventEnd': 225,
            'redirectStart': 1, 'redirectEnd': 11, 'redirectCount': 2,
            'name': 'https://private/?answer=UNIT', 'secret': 'UNIT'}}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            log_navigation_timing(config(), snapshot)
        self.assertEqual(output.getvalue(), '[NAV_TIMING] nav_entry_available=1 '
                         'nav_to_request_ms=20.0 request_to_response_ms=100.0 '
                         'response_download_ms=30.0 response_end_to_dcl_ms=75.0 '
                         'nav_to_dcl_ms=225.0 redirect_timing_available=1 '
                         'redirect_ms=10.0 redirect_count=2\n')

    def test_navigation_timing_disabled_and_fail_open(self):
        class Untouchable:
            def get(self, key):
                raise AssertionError('disabled logger must not inspect snapshot')
        with patch('builtins.print') as printer:
            log_navigation_timing(config(False), Untouchable())
            printer.assert_not_called()
        for bad in (None, [], Untouchable()):
            log_navigation_timing(config(), bad)
        with patch('builtins.print', side_effect=OSError('private output failure')):
            log_navigation_timing(config(), {})

    def test_navigation_timing_rejects_malformed_and_unavailable_values(self):
        for invalid in ('https://private/UNIT', True, float('nan'), float('inf'), -1, {}):
            with self.subTest(invalid=invalid):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    log_navigation_timing(config(), {'navigation_timing': {
                        'startTime': 0, 'requestStart': invalid, 'responseStart': invalid,
                        'responseEnd': invalid, 'domContentLoadedEventEnd': invalid,
                        'redirectStart': invalid, 'redirectEnd': invalid, 'redirectCount': invalid}})
                self.assertEqual(output.getvalue(), '[NAV_TIMING] nav_entry_available=1 '
                                 'redirect_timing_available=0\n')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            log_navigation_timing(config(), {'navigation_timing': {
                'startTime': 0, 'requestStart': 50, 'responseStart': 20,
                'responseEnd': 0, 'domContentLoadedEventEnd': 0,
                'redirectStart': 0, 'redirectEnd': 0, 'redirectCount': 0}})
            log_navigation_timing(config(), {'navigation_timing': {'name': 'UNIT'}})
        self.assertEqual(output.getvalue(), '[NAV_TIMING] nav_entry_available=1 '
                         'nav_to_request_ms=50.0 redirect_timing_available=0 redirect_count=0\n'
                         '[NAV_TIMING] nav_entry_available=0\n')

    def test_duration_silent_mode_and_logger_failure(self):
        output = io.StringIO()
        with patch('flow_timing.time.perf_counter', side_effect=[1.0, 1.125]), contextlib.redirect_stdout(output):
            with flow_stage(config(), 'date_scan') as timing:
                timing.outcome, timing.count = 'matched', 2
        self.assertEqual(output.getvalue(), f'[STAGE] stage=date_scan pid={os.getpid()} start_ms=1000.0 end_ms=1125.0 duration_ms=125.0 outcome=matched count=2\n')
        with patch('flow_timing.time.perf_counter', side_effect=AssertionError('must stay off')), patch('builtins.print') as printer:
            with flow_stage(config(False), 'date_scan'):
                pass
            printer.assert_not_called()
        with patch('builtins.print', side_effect=OSError('closed output')):
            with flow_stage(config(), 'date_scan'):
                result = 42
        self.assertEqual(result, 42)

    def test_exception_identity_preserved_and_private_details_absent(self):
        error = RuntimeError('secret query ?token=private answer=UNIT')
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(RuntimeError) as caught:
            with flow_stage(config(), 'submit_input_dispatch'):
                raise error
        self.assertIs(caught.exception, error)
        self.assertIn('outcome=error', output.getvalue())
        self.assertNotIn('secret', output.getvalue())
        with contextlib.redirect_stdout(output), patch('builtins.print', side_effect=OSError('closed')):
            with self.assertRaises(RuntimeError) as caught:
                with flow_stage(config(), 'date_scan'):
                    raise error
        self.assertIs(caught.exception, error)

    def test_rejects_free_text_fields(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with flow_stage(config(), 'https://host/?secret=token'):
                pass
        self.assertEqual(output.getvalue(), '')

    def run_flow(self, instrumented=True, enabled=True, **tab_options):
        ns, tab, cfg = load_functions(instrumented), FakeTab(**tab_options), config(enabled)
        ocr = types.SimpleNamespace(classification=lambda image: 'UNIT')
        async def run():
            ns['reset_timing']()
            selected = await ns['nodriver_tixcraft_date_auto_select'](tab, tab.url, cfg, 'indievox.com')
            if '/ticket/area/' in tab.url:
                ns['reset_timing']()
                await ns['nodriver_tixcraft_area_auto_select'](tab, tab.url, cfg)
            ns['reset_timing']()
            await ns['nodriver_tixcraft_ticket_main'](tab, cfg, ocr, None, 'indievox.com')
            return selected, tab.quantity, tab.agreed, tab.dispatch_result
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = asyncio.run(run())
        return result, tab.calls, output.getvalue()

    def test_date_area_form_dispatch_and_equivalence(self):
        result, calls, logs = self.run_flow()
        baseline, original_calls, _ = self.run_flow(instrumented=False)
        disabled, disabled_calls, silent_logs = self.run_flow(enabled=False)
        self.assertEqual(result, (True, '2', True, (False, True)))
        self.assertEqual(result, baseline)
        self.assertEqual(result, disabled)
        self.assertEqual(calls, original_calls)
        self.assertEqual(calls, disabled_calls)
        self.assertEqual(silent_logs, '')
        self.assertEqual([c for c in calls if c[0] == 'send'], [('send', 'keyDown'), ('send', 'keyUp')])
        self.assertRegex(logs, r'stage=area_scan .*outcome=no_match priority=1 count=0')
        self.assertRegex(logs, r'stage=area_scan .*outcome=matched priority=2 count=1')
        self.assertRegex(logs, r'stage=form_prepare .*outcome=ready')
        self.assertRegex(logs, r'stage=submit_input_dispatch .*outcome=dispatched')
        self.assertIn('[T] T_form_submitted:', logs)
        self.assertNotIn('UNIT', logs)
        self.assertNotIn('https://', logs)

    def test_direct_ticket_redirect_bypasses_area(self):
        result, calls, logs = self.run_flow(direct_ticket=True)
        self.assertEqual(result[-1], (False, True))
        self.assertNotIn('stage=area_', logs)
        self.assertRegex(logs, r'stage=submit_input_dispatch .*outcome=dispatched')

    def test_two_select_shape_skips_disabled_sold_out_option(self):
        ns, tab = load_functions(), FakeTab()
        tab.url = 'https://indievox.com/ticket/ticket/unit/1/1/1'
        with contextlib.redirect_stdout(io.StringIO()):
            result = asyncio.run(ns['nodriver_tixcraft_assign_ticket_number'](tab, config()))
        self.assertEqual(result, (False, None, 'TicketForm_ticketPrice_01'))

    def test_area_no_keyword_and_fallback_are_single_scans(self):
        for keywords, fallback, expected_stage in [('', False, 'area_scan'), ('"missing"', True, 'area_fallback_scan')]:
            with self.subTest(keywords=keywords):
                ns, tab, cfg = load_functions(), FakeTab(), config()
                cfg['area_auto_select']['area_keyword'] = keywords
                cfg['area_auto_fallback'] = fallback
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    asyncio.run(ns['nodriver_tixcraft_area_auto_select'](tab, tab.url, cfg))
                lines = [line for line in output.getvalue().splitlines() if f'stage={expected_stage} ' in line]
                self.assertEqual(len(lines), 1)
                self.assertIn('outcome=matched', lines[0])
                if fallback:
                    self.assertNotIn('priority=0', output.getvalue())
                else:
                    self.assertIn('priority=0', lines[0])

    def test_not_ready_never_dispatches(self):
        result, calls, logs = self.run_flow(ready=False)
        self.assertEqual(result[-1], (False, False))
        self.assertFalse(any(c[0] == 'send' for c in calls))
        self.assertRegex(logs, r'stage=form_prepare .*outcome=not_ready')
        self.assertNotIn('stage=submit_input_dispatch', logs)

    def test_failed_keyup_is_not_reported_dispatched(self):
        result, calls, logs = self.run_flow(fail_send='keyUp')
        baseline, original_calls, _ = self.run_flow(instrumented=False, fail_send='keyUp')
        self.assertEqual(result[-1], (False, False))
        self.assertEqual((result, calls), (baseline, original_calls))
        self.assertRegex(logs, r'stage=submit_input_dispatch .*outcome=error')
        self.assertNotIn('outcome=dispatched', logs)
        self.assertNotIn('private detail', logs)

    def test_prefill_verified_and_invalid_marker_paths(self):
        for verified in (True, False):
            with self.subTest(verified=verified):
                result, calls, logs = self.run_flow(prefill=True, verify_prefill=verified)
                self.assertEqual(result[-1], (False, True))
                self.assertRegex(logs, r'stage=prefill_verify .*outcome=' + ('verified' if verified else 'not_verified'))
                self.assertEqual('stage=ticket_prepare' in logs, not verified)

    def test_capture_and_classification_failure_are_separate(self):
        ns, tab = load_functions(), FakeTab()
        def fail(image):
            self.assertEqual(image, b'unit-only-image')
            raise ValueError('private classification contents')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            answer = asyncio.run(ns['nodriver_tixcraft_get_ocr_answer'](tab, types.SimpleNamespace(classification=fail), 'canvas', None, 'indievox.com', config()))
        self.assertIsNone(answer)
        self.assertRegex(output.getvalue(), r'stage=ocr_capture .*outcome=captured')
        self.assertRegex(output.getvalue(), r'stage=ocr_classify .*outcome=error')
        self.assertNotIn('private classification', output.getvalue())


if __name__ == '__main__':
    unittest.main()
