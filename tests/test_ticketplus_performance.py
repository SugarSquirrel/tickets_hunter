"""Refresh lifecycle regressions. Run: python -m unittest discover -s tests."""
import asyncio
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from platforms import ticketplus as tp


class FakeTab:
    def __init__(self):
        self.target = SimpleNamespace(url="https://ticketplus.com.tw/order/event/session")
        self.handlers = {}
        self.state = {"observed": True, "busy": False}
        self.evaluate = AsyncMock(side_effect=lambda *a, **kw: json.dumps(self.state))
        self.send = AsyncMock()
        self.button = SimpleNamespace(click=AsyncMock())
        self.query_selector = AsyncMock(return_value=self.button)

    def add_handler(self, event_type, callback):
        self.handlers[event_type] = callback


class RefreshTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tp._state.clear()
        self.tab = FakeTab()
        self.debug = SimpleNamespace(log=lambda *args: None)
        self.now = Mock(return_value=100.0)
        self.clock = patch.object(tp, "time", SimpleNamespace(monotonic=self.now, time=time.time))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    async def click(self):
        self.assertTrue(await tp._ticketplus_click_refresh_button(self.tab, self.debug))

    async def request(self, request_id="stock", url="https://apis.ticketplus.com.tw/order/api/v1/get"):
        callback = self.tab.handlers[tp.cdp.network.RequestWillBeSent]
        await callback(SimpleNamespace(type_=tp.cdp.network.ResourceType.FETCH,
                                       request=SimpleNamespace(url=url), request_id=request_id))

    async def test_inflight_request_blocks_selection_even_if_vue_is_idle(self):
        await self.click()
        await self.request()
        calls_before = self.tab.evaluate.await_count
        self.assertFalse(await tp._ticketplus_refresh_is_ready(self.tab, self.debug))
        self.assertEqual(self.tab.evaluate.await_count, calls_before)

    async def test_all_refresh_requests_must_finish(self):
        await self.click()
        await self.request("areas")
        await self.request("products")
        finish = self.tab.handlers[tp.cdp.network.LoadingFinished]
        await finish(SimpleNamespace(request_id="areas"))
        self.now.return_value = 100.2
        self.assertFalse(await tp._ticketplus_refresh_is_ready(self.tab, self.debug))
        await finish(SimpleNamespace(request_id="products"))
        self.now.return_value = 100.3
        self.assertTrue(await tp._ticketplus_refresh_is_ready(self.tab, self.debug))

    async def test_vue_patch_must_finish_after_network(self):
        await self.click()
        await self.request()
        await self.tab.handlers[tp.cdp.network.LoadingFinished](SimpleNamespace(request_id="stock"))
        self.tab.state["busy"] = True
        self.now.return_value = 100.3
        self.assertFalse(await tp._ticketplus_refresh_is_ready(self.tab, self.debug))
        self.tab.state["busy"] = False
        self.assertTrue(await tp._ticketplus_refresh_is_ready(self.tab, self.debug))

    async def test_failed_request_does_not_leave_permanent_lock(self):
        await self.click()
        await self.request()
        await self.tab.handlers[tp.cdp.network.LoadingFailed](SimpleNamespace(request_id="stock"))
        self.now.return_value = 100.2
        self.assertTrue(await tp._ticketplus_refresh_is_ready(self.tab, self.debug))

    async def test_duplicate_refresh_does_not_click_or_install_handlers_again(self):
        await self.click()
        await self.click()
        self.tab.button.click.assert_awaited_once()
        self.tab.send.assert_awaited_once()

    async def test_background_analytics_is_not_a_refresh_request(self):
        await self.click()
        await self.request(url="https://www.clarity.ms/collect")
        self.now.return_value = 100.2
        self.assertTrue(await tp._ticketplus_refresh_is_ready(self.tab, self.debug))

    async def test_unknown_layout_keeps_bounded_settle_fallback(self):
        await self.click()
        self.tab.state["observed"] = False
        self.now.return_value = 100.1
        self.assertFalse(await tp._ticketplus_refresh_is_ready(self.tab, self.debug))
        self.now.return_value = 100.2
        self.assertTrue(await tp._ticketplus_refresh_is_ready(self.tab, self.debug))

    async def test_stalled_refresh_and_navigation_release_state(self):
        await self.click()
        await self.request()
        self.now.return_value = 100 + tp.CONST_TICKETPLUS_REFRESH_TIMEOUT_SEC
        self.assertTrue(await tp._ticketplus_refresh_is_ready(self.tab, self.debug))
        await self.click()
        self.tab.target.url = "https://ticketplus.com.tw/confirm/event/session"
        self.assertTrue(await tp._ticketplus_refresh_is_ready(self.tab, self.debug))
        self.assertNotIn("refresh_pending", tp._state)

    async def test_queue_gate_preserves_position_and_never_selects(self):
        queue = {"in_queue": True, "degraded": False, "source": "vue"}
        with patch.object(tp, "nodriver_ticketplus_read_queue_state", AsyncMock(return_value=queue)), \
             patch.object(tp, "nodriver_ticketplus_unified_select", AsyncMock()) as select:
            await tp.nodriver_ticketplus_order(self.tab, {"advanced": {"verbose": False}}, None, None)
            select.assert_not_awaited()

    async def test_order_does_not_select_or_refresh_again_while_data_is_loading(self):
        await self.click()
        self.tab.state["busy"] = True
        queue = {"in_queue": False, "degraded": False, "source": "vue"}
        with patch.object(tp, "nodriver_ticketplus_read_queue_state", AsyncMock(return_value=queue)), \
             patch.object(tp, "nodriver_ticketplus_unified_select", AsyncMock()) as select:
            for _ in range(3):
                await tp.nodriver_ticketplus_order(self.tab, {"advanced": {"verbose": False}}, None, None)
            select.assert_not_awaited()
            self.tab.button.click.assert_awaited_once()

    async def test_refresh_interval_includes_scan_time_and_respects_changes(self):
        self.now.return_value = 100.4
        self.assertFalse(tp._ticketplus_refresh_due(self.tab, 0.5, 100.0))
        self.now.return_value = 100.5
        self.assertTrue(tp._ticketplus_refresh_due(self.tab, 0.5, 100.4))
        tp._ticketplus_note_refresh(self.tab)
        self.now.return_value = 100.9
        self.assertFalse(tp._ticketplus_refresh_due(self.tab, 0.5, 100.6))
        # A live setting change takes effect without an old cached deadline.
        self.assertTrue(tp._ticketplus_refresh_due(self.tab, 0.2, 100.6))
        self.now.return_value = 101.0
        self.assertTrue(tp._ticketplus_refresh_due(self.tab, 0.5, 100.9))

    async def test_refresh_schedule_resets_when_page_changes(self):
        tp._ticketplus_note_refresh(self.tab)
        self.tab.target.url = "https://ticketplus.com.tw/order/event/other-session"
        self.now.return_value = 102.1
        self.assertFalse(tp._ticketplus_refresh_due(self.tab, 0.5, 102.0))
        self.now.return_value = 102.5
        self.assertTrue(tp._ticketplus_refresh_due(self.tab, 0.5, 102.1))

    async def test_order_paces_refreshes_without_adding_interval_to_each_scan(self):
        cfg = {"advanced": {"verbose": False, "auto_reload_page_interval": 0.5},
               "area_auto_select": {"area_keyword": '"missing"'}}
        times = iter([100.4, 100.5, 100.7, 101.0])

        async def scan(*args):
            self.now.return_value = next(times)
            return False

        queue = {"in_queue": False, "degraded": False, "source": "vue"}
        with patch.object(tp, "nodriver_ticketplus_read_queue_state", AsyncMock(return_value=queue)), \
             patch.object(tp, "check_and_handle_pause", AsyncMock(return_value=False)), \
             patch.object(tp, "nodriver_ticketplus_unified_select", side_effect=scan), \
             patch.object(tp, "nodriver_ticketplus_detect_layout_style", AsyncMock()) as layout, \
             patch.object(tp, "nodriver_ticketplus_check_next_button", AsyncMock()) as button:
            for expected_clicks in (0, 1, 1, 2):
                await tp.nodriver_ticketplus_order(self.tab, cfg, None, None)
                self.assertEqual(self.tab.button.click.await_count, expected_clicks)
            layout.assert_not_awaited()
            button.assert_not_awaited()

    async def test_activity_page_uses_deadline_and_keeps_one_second_default(self):
        cfg = {"advanced": {"verbose": False, "auto_reload_page_interval": 0},
               "date_auto_select": {"mode": "from top to bottom", "date_keyword": ""},
               "tixcraft": {"pass_date_is_sold_out": False, "auto_reload_coming_soon_page": True}}
        self.tab.query_selector_all = AsyncMock(return_value=[])
        with patch.object(tp, "_ticketplus_click_refresh_button", AsyncMock(return_value=True)) as refresh:
            await tp.nodriver_ticketplus_date_auto_select(self.tab, cfg)
            refresh.assert_not_awaited()
            self.now.return_value = 100.9
            await tp.nodriver_ticketplus_date_auto_select(self.tab, cfg)
            refresh.assert_not_awaited()
            self.now.return_value = 101.0
            await tp.nodriver_ticketplus_date_auto_select(self.tab, cfg)
            refresh.assert_awaited_once()

    async def test_debug_uses_layout_status_without_a_second_button_read(self):
        cfg = {"advanced": {"verbose": True, "auto_reload_page_interval": -1},
               "area_auto_select": {"area_keyword": ""}}
        queue = {"in_queue": False, "degraded": False, "source": "vue"}
        with patch.object(tp.util, "create_debug_logger", return_value=SimpleNamespace(enabled=True, log=lambda *a: None)), \
             patch.object(tp, "nodriver_ticketplus_read_queue_state", AsyncMock(return_value=queue)), \
             patch.object(tp, "check_and_handle_pause", AsyncMock(return_value=False)), \
             patch.object(tp, "nodriver_ticketplus_unified_select", AsyncMock(return_value=False)), \
             patch.object(tp, "nodriver_ticketplus_detect_layout_style", AsyncMock(return_value={"style": 1})) as layout, \
             patch.object(tp, "nodriver_ticketplus_check_next_button", AsyncMock()) as button:
            await tp.nodriver_ticketplus_order(self.tab, cfg, None, None)
            layout.assert_awaited_once()
            button.assert_not_awaited()

    async def test_stalled_popup_read_returns_unknown_then_recovers(self):
        async def stalled(*args, **kwargs):
            await asyncio.Event().wait()

        self.tab.evaluate.side_effect = stalled
        with patch.object(tp, "CONST_TICKETPLUS_CDP_TIMEOUT_SEC", 0.02):
            self.assertIsNone(await tp.nodriver_ticketplus_accept_order_fail(self.tab, self.debug))
        self.tab.evaluate.side_effect = lambda *args, **kwargs: {"foundFailure": False}
        self.assertFalse(await tp.nodriver_ticketplus_accept_order_fail(self.tab, self.debug))

    async def test_inventory_completion_ignores_unrelated_page_work(self):
        replies = iter([{"native": True}, {"owned": True, "pending": False, "error": None}])
        self.tab.evaluate.side_effect = lambda *a, **kw: json.dumps(next(replies))
        await self.click()
        self.assertEqual(tp._state["refresh_pending"]["kind"], "inventory")
        self.assertTrue(await tp._ticketplus_refresh_is_ready(self.tab, self.debug))
        self.tab.button.click.assert_not_awaited()
        self.tab.send.assert_not_awaited()
        self.assertFalse(tp._state["refresh_failed"])

    async def test_inventory_inflight_prevents_overlap(self):
        replies = iter([{"native": True}, {"owned": True, "pending": True}])
        self.tab.evaluate.side_effect = lambda *a, **kw: json.dumps(next(replies))
        await self.click()
        self.assertFalse(await tp._ticketplus_refresh_is_ready(self.tab, self.debug))
        await self.click()
        self.assertEqual(self.tab.evaluate.await_count, 2)
        self.tab.button.click.assert_not_awaited()

    async def test_inventory_error_does_not_select_stale_tickets(self):
        replies = iter([{"native": True}, {"owned": True, "pending": False, "error": "request failed"}])
        self.tab.evaluate.side_effect = lambda *a, **kw: json.dumps(next(replies))
        await self.click()
        cfg = {"advanced": {"verbose": False, "auto_reload_page_interval": -1},
               "area_auto_select": {"area_keyword": ""}}
        queue = {"in_queue": False, "degraded": False, "source": "vue"}
        with patch.object(tp, "nodriver_ticketplus_read_queue_state", AsyncMock(return_value=queue)), \
             patch.object(tp, "check_and_handle_pause", AsyncMock(return_value=False)), \
             patch.object(tp, "nodriver_ticketplus_unified_select", AsyncMock()) as select:
            await tp.nodriver_ticketplus_order(self.tab, cfg, None, None)
            select.assert_not_awaited()

    async def test_stalled_inventory_reloads_once_only_when_not_queued(self):
        for queued in (True, False):
            tp._state.clear()
            tp._state["refresh_pending"] = {"kind": "inventory", "url": self.tab.target.url, "started": 80.0}
            self.tab.reload = AsyncMock()
            cfg = {"advanced": {"verbose": False, "auto_reload_page_interval": 0},
                   "area_auto_select": {"area_keyword": ""}}
            queue = {"in_queue": queued, "degraded": False, "source": "vue"}
            with patch.object(tp, "nodriver_ticketplus_read_queue_state", AsyncMock(return_value=queue)), \
                 patch.object(tp, "check_and_handle_pause", AsyncMock(return_value=False)), \
                 patch.object(tp, "nodriver_ticketplus_unified_select", AsyncMock()) as select:
                await tp.nodriver_ticketplus_order(self.tab, cfg, None, None)
                self.assertEqual(self.tab.reload.await_count, 0 if queued else 1)
                select.assert_not_awaited()

    async def test_stalled_main_page_read_never_selects_or_submits(self):
        async def stalled(*args, **kwargs):
            await asyncio.Event().wait()

        tp._state.update(fail_list=[], spa_mounted=True, order_page_visited=True)
        self.tab.evaluate.side_effect = stalled
        cfg = {"advanced": {"verbose": False}}
        with patch.object(tp, "CONST_TICKETPLUS_CDP_TIMEOUT_SEC", 0.02), \
             patch.object(tp, "nodriver_ticketplus_accept_realname_card", AsyncMock(return_value=False)), \
             patch.object(tp, "nodriver_ticketplus_order", AsyncMock()) as order:
            status = await tp.nodriver_ticketplus_main(self.tab, self.tab.target.url, cfg, None, None)
            order.assert_not_awaited()
            self.assertFalse(status["purchase_completed"])

    async def test_lost_refresh_click_reply_keeps_inflight_guard(self):
        async def stalled():
            await asyncio.Event().wait()

        self.tab.button.click.side_effect = stalled
        with patch.object(tp, "CONST_TICKETPLUS_CDP_TIMEOUT_SEC", 0.02):
            await self.click()
        self.assertIn("refresh_pending", tp._state)
        await self.click()
        self.tab.button.click.assert_awaited_once()

    async def test_stalled_delay_is_bounded_and_cancellation_is_not_swallowed(self):
        async def stalled(*args):
            await asyncio.Event().wait()

        with patch.object(tp, "sleep_with_pause_check", stalled), \
             patch.object(tp, "CONST_TICKETPLUS_CDP_TIMEOUT_SEC", 0.02):
            with self.assertRaises(asyncio.TimeoutError):
                await tp._ticketplus_pause_delay(self.tab, 0, {})
        self.tab.evaluate.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await tp._ticketplus_evaluate(self.tab, "true")


if __name__ == "__main__":
    unittest.main()
