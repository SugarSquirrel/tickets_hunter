"""Offline document/redirect races; no browser, settings, network or submission."""

import asyncio
import ast
import contextlib
import io
import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from tixcraft_readiness import (DOCUMENT_SNAPSHOT_JS, document_route, navigate_date,
                               supported_url, wait_ticket_select)
from test_flow_timing import FakeTab, config, load_functions


GAME = 'https://www.indievox.com/activity/game/unit'
AREA = 'https://www.indievox.com/ticket/area/unit/1'
TICKET = 'https://www.indievox.com/ticket/ticket/unit/1/1/1'
CFG = {'advanced': {'show_timing_log': False}}


def doc(url, generation=2, ready=True, **keys):
    return dict(href=url, document_id=generation, dom_ready=ready, **keys)


class NavigationTab:
    """Sequence includes the pre-navigation document and later commits.

    Cached target URL deliberately lags actual document until update_target().
    These are CDP results, not execution/validation of the JS on a real site.
    """
    def __init__(self, snapshots, error=None, response=None):
        self.snapshots = list(snapshots)
        self.last = None
        self.calls = []
        self.error, self.response = error, response
        self.target = types.SimpleNamespace(url=GAME)

    async def evaluate(self, js):
        self.assert_snapshot_script(js)
        self.calls.append('snapshot')
        if self.snapshots:
            self.last = self.snapshots.pop(0)
        if isinstance(self.last, Exception):
            raise self.last
        return self.last

    @staticmethod
    def assert_snapshot_script(js):
        if js != DOCUMENT_SNAPSHOT_JS:
            raise AssertionError('Unexpected script')

    async def send(self, command):
        self.calls.append(('navigate', command))
        if self.error:
            raise self.error
        return self.response

    async def get(self, url):
        self.calls.append(('legacy_get', url))

    async def wait(self):
        self.calls.append('idle_wait')

    async def update_target(self):
        self.calls.append('update_target')
        self.target.url = self.last['href']

    async def wait_for(self, selector, timeout):
        self.calls.append(('legacy_select_wait', timeout))


class RouteTests(unittest.TestCase):
    def test_membership_verification_dispatch_is_preserved(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'src/platforms/tixcraft.py').read_text(encoding='utf-8'))
        main = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'nodriver_tixcraft_main')
        expected = ast.parse("if '/ticket/verify/' in url:\n    _state['fail_list'] = await nodriver_tixcraft_verify(tab, config_dict, _state['fail_list'])\nelse:\n    _state['fail_list'] = []").body[0]
        self.assertTrue(any(ast.dump(node) == ast.dump(expected) for node in ast.walk(main)))

    def test_domain_and_route_boundaries(self):
        for url in ['https://tixcraft.com/ticket/area/a', AREA,
                    'https://tickets.indievox.com/login']:
            self.assertTrue(supported_url(url))
        for url in ['https://indievox.com.evil.test/ticket/area/a',
                    'https://evilindievox.com/ticket/area/a',
                    'https://indievox.com@evil.test/login',
                    'https://user@indievox.com/login',
                    'https://indievox.com:8443/login',
                    'javascript:location="https://indievox.com/login"',
                    'https://ticketmaster.sg/ticket/area/a']:
            self.assertFalse(supported_url(url))
        self.assertIsNone(document_route('https://indievox.com/login-lookalike'))
        self.assertIsNone(document_route('https://indievox.com/?next=/ticket/area/a'))
        self.assertEqual(document_route('https://indievox.com/ticket/verify/a'), 'verify')


class ReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def navigate(self, tab, href=AREA, **kwargs):
        return await navigate_date(tab, href, GAME, CFG, lambda url: url,
                                   poll_interval=0, **kwargs)

    async def test_area_ticket_verify_and_social_login_redirects(self):
        for route, url in [('area', AREA), ('ticket', TICKET),
                           ('verify', 'https://tixcraft.com/ticket/verify/unit'),
                           ('login', 'https://www.indievox.com/login')]:
            with self.subTest(route=route):
                tab = NavigationTab([doc(GAME, 1), doc(GAME, 1, area=True),
                                     doc(url, ready=False, **{route: True}),
                                     doc(url, **{route: True})])
                self.assertEqual(await self.navigate(tab), 'ready_' + route)
                self.assertEqual(tab.target.url, url)
                self.assertEqual(sum(isinstance(c, tuple) and c[0] == 'navigate' for c in tab.calls), 1)
                self.assertNotIn('idle_wait', tab.calls)

    async def test_navigation_metrics_do_not_add_browser_calls_or_change_readiness(self):
        baseline_calls = None
        for metrics in (None, 'https://private/UNIT', {'requestStart': float('nan')},
                        {'startTime': 0, 'requestStart': 5, 'responseStart': 20,
                         'responseEnd': 30, 'domContentLoadedEventEnd': 45}):
            for enabled in (False, True):
                tab = NavigationTab([doc(GAME, 1), doc(AREA, area=True,
                                     navigation_timing=metrics)])
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = await navigate_date(tab, AREA, GAME, config(enabled), lambda url: url,
                                                 poll_interval=0)
                self.assertEqual(result, 'ready_area')
                self.assertEqual(tab.calls, ['snapshot', ('navigate', AREA), 'snapshot', 'update_target'])
                if baseline_calls is None:
                    baseline_calls = tab.calls
                self.assertEqual(tab.calls, baseline_calls)
                logs = output.getvalue()
                self.assertEqual(logs.count('[NAV_TIMING]'), int(enabled))
                self.assertEqual('stage=date_target_cache_update ' in logs, enabled)
                self.assertNotIn('https://', logs)
                self.assertNotIn('UNIT', logs)
        tab = NavigationTab([doc(GAME, 1), doc(AREA, area=True)])
        with patch('builtins.print', side_effect=OSError('closed')):
            self.assertEqual(await navigate_date(tab, AREA, GAME, config(), lambda url: url), 'ready_area')
        self.assertEqual(tab.calls, baseline_calls)

    async def test_interactive_dcl_completed_does_not_wait_resource_idle(self):
        # dom_ready=True models interactive + DCL event end > 0, with images
        # still loading. The helper must not add listener idle or complete waits.
        tab = NavigationTab([doc(GAME, 1), doc(AREA, area=True)])
        self.assertEqual(await self.navigate(tab), 'ready_area')
        self.assertNotIn('idle_wait', tab.calls)

    async def test_old_dom_same_document_and_missing_selectors_use_idle(self):
        for snapshot in [doc(AREA, 1, area=True), doc(AREA, area=False),
                         doc(AREA, ready=False, area=True)]:
            with self.subTest(snapshot=snapshot):
                tab = NavigationTab([doc(GAME, 1), snapshot])
                self.assertEqual(await self.navigate(tab, timeout=0), 'idle_timeout')
                self.assertEqual(tab.calls.count('idle_wait'), 1)
                self.assertFalse(any(isinstance(c, tuple) and c[0] == 'legacy_get' for c in tab.calls))

    async def test_relative_destination_and_allowed_family_redirect(self):
        tab = NavigationTab([doc(GAME, 1), doc('https://tixcraft.com/ticket/ticket/a', ticket=True)])
        self.assertEqual(await self.navigate(tab, '/ticket/area/unit/1'), 'ready_ticket')
        self.assertIn(('navigate', AREA), tab.calls)

    async def test_navigation_errors_unknown_redirects_and_lost_context_do_not_renavigate(self):
        for tab in [NavigationTab([doc(GAME, 1)], error=RuntimeError('transport')),
                    NavigationTab([doc(GAME, 1)], response=('frame', None, 'blocked', False)),
                    NavigationTab([doc(GAME, 1), doc('https://example.com/login')]),
                    NavigationTab([doc(GAME, 1), RuntimeError('context destroyed')])]:
            with self.subTest(tab=tab):
                result = await self.navigate(tab, timeout=0)
                self.assertTrue(result.startswith('idle_'))
                self.assertEqual(sum(isinstance(c, tuple) and c[0] == 'navigate' for c in tab.calls), 1)
                self.assertEqual(tab.calls.count('idle_wait'), 1)
                self.assertFalse(any(isinstance(c, tuple) and c[0] == 'legacy_get' for c in tab.calls))

    async def test_unsupported_target_and_missing_preflight_use_old_get(self):
        for snapshots, href in [([doc(GAME, 1)], 'https://example.com/ticket/area/a'),
                                ([None], AREA)]:
            tab = NavigationTab(snapshots)
            self.assertTrue((await self.navigate(tab, href)).startswith('legacy_'))
            self.assertIn(('legacy_get', href), tab.calls)
            self.assertFalse(any(isinstance(c, tuple) and c[0] == 'navigate' for c in tab.calls))

    async def test_stale_ticket_selector_wait_exits_on_login_or_new_document(self):
        for changed in [doc('https://www.indievox.com/login'), doc(TICKET, 3, select=True)]:
            tab = NavigationTab([doc(TICKET, select=False), changed])
            self.assertFalse(await wait_ticket_select(tab, TICKET, poll_interval=0))
            self.assertEqual(tab.calls, ['snapshot', 'snapshot'])

    async def test_same_document_slow_select_and_failed_submit_can_retry(self):
        tab = NavigationTab([doc(TICKET, select=False), doc(TICKET, select=True)])
        self.assertTrue(await wait_ticket_select(tab, TICKET, poll_interval=0))
        # A previous unsuccessful submit does not suppress the next attempt.
        self.assertTrue(await wait_ticket_select(tab, TICKET, poll_interval=0))
        tab = NavigationTab([doc(TICKET, select=False)])
        self.assertTrue(await wait_ticket_select(tab, TICKET, timeout=0))
        self.assertNotIn('idle_wait', tab.calls)

    async def test_ticket_main_skips_live_login_despite_cached_ticket_route(self):
        ns, tab = load_functions(), FakeTab()
        tab.url = TICKET  # nodriver_current_url mock behaves as a stale cache.
        evaluate = tab.evaluate

        async def snapshot_login(js, **kwargs):
            if js == DOCUMENT_SNAPSHOT_JS:
                return doc('https://www.indievox.com/login')
            return await evaluate(js, **kwargs)

        tab.evaluate = snapshot_login
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            await ns['nodriver_tixcraft_ticket_main'](tab, config(), None, None, 'indievox.com')
        self.assertRegex(output.getvalue(), r'stage=ticket_document_guard .*outcome=document_changed')
        self.assertEqual(tab.calls, [])

    async def test_ticket_main_stops_if_document_leaves_during_selector_wait(self):
        ns, tab = load_functions(), FakeTab()
        tab.url = TICKET
        evaluate = tab.evaluate
        snapshots = [doc(TICKET, select=False), doc(TICKET, select=False),
                     doc('https://www.indievox.com/login')]

        async def race(js, **kwargs):
            if js == DOCUMENT_SNAPSHOT_JS:
                return snapshots.pop(0) if len(snapshots) > 1 else snapshots[0]
            return await evaluate(js, **kwargs)

        tab.evaluate = race
        with contextlib.redirect_stdout(io.StringIO()):
            await ns['nodriver_tixcraft_ticket_main'](tab, config(False), None, None, 'indievox.com')
        self.assertFalse(any(c[0] in ('reload', 'send') for c in tab.calls))
        self.assertFalse(any(c[0] == 'evaluate' and 'const targetOption' in c[1] for c in tab.calls))

    async def test_paused_assign_returns_consistent_tuple(self):
        ns = load_functions()

        async def paused(config):
            return True

        ns['check_and_handle_pause'] = paused
        self.assertEqual(await ns['nodriver_tixcraft_assign_ticket_number'](FakeTab(), config(False)),
                         (False, None, None))

    async def test_same_ticket_page_failed_dispatch_and_captcha_retry_still_run(self):
        for failed_dispatch in (False, True):
            with self.subTest(failed_dispatch=failed_dispatch):
                ns, tab, cfg = load_functions(), FakeTab(fail_send='keyUp' if failed_dispatch else None), config(False)
                tab.url = TICKET
                ocr = types.SimpleNamespace(classification=lambda image: 'UNIT')
                await ns['nodriver_tixcraft_ticket_main'](tab, cfg, ocr, None, 'indievox.com')
                self.assertEqual(tab.dispatch_result, (False, not failed_dispatch))
                # Simulate server rejecting a same-page submission or the
                # existing alert listener marking a wrong synthetic answer.
                ns['_state'].update(form_submitted_at=time.time(), ocr_completed_url=TICKET,
                                    captcha_alert_detected=True)
                tab.fail_send = None
                await ns['nodriver_tixcraft_ticket_main'](tab, cfg, ocr, None, 'indievox.com')
                self.assertEqual(tab.dispatch_result, (False, True))
                self.assertFalse(ns['_state']['captcha_alert_detected'])
                self.assertEqual(sum(c[0] == 'send' for c in tab.calls), 4)
                self.assertFalse(any(c[0] == 'reload' for c in tab.calls))
