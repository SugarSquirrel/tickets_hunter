"""Offline controller regression tests; no requests to a ticket website."""
import copy
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from platforms import kham_flow as flow

BASE = "https://kham.com.tw/application/UTK02/"
DATE = BASE + "UTK0201_00.aspx?PRODUCT_ID=SHOW"
CART = BASE + "UTK0206_.aspx"


def config():
    return {"ticket_number": 2, "date_auto_select": {"enable": True, "date_keyword": '"10/03"'},
            "area_auto_select": {"enable": True, "area_keyword": '"VIP"'},
            "keyword_exclude": '"身障"', "ocr_captcha": {"enable": True},
            "advanced": {"auto_reload_page_interval": 0.25, "play_sound": {"order": False}},
            "kham": {"ticket_queue": [
                {"ticket_number": 2, "date_keyword": '"10/03"', "area_keyword": '"VIP"'},
                {"ticket_number": 1, "date_keyword": '"10/04"', "area_keyword": '"B區"'}]}}


class Tab:
    def __init__(self, url=DATE):
        self.target = SimpleNamespace(url=url)
        self.visits = []
        self.dialog = ""
        self.groups = []
        self.quantity = 2
        self.submits = 0
        self.captcha = "1234"

    async def get(self, url):
        self.visits.append(url)
        self.target.url = url

    async def reload(self):
        self.visits.append(self.target.url)

    async def evaluate(self, script):
        return self.captcha

    async def snapshot(self):
        return {"url": self.target.url, "ready": True, "dialog": self.dialog,
                "quantity": self.quantity, "has_quantity": "0205" in self.target.url,
                "has_seats": False, "has_types": False, "cart_groups": self.groups,
                "cart_ready": "0206" in self.target.url,
                "login": False, "busy": False}


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tab = Tab()
        self.config = config()
        self.legacy = SimpleNamespace(
            nodriver_kham_product=AsyncMock(), nodriver_kham_performance=AsyncMock(),
            nodriver_kham_go_buy_redirect=AsyncMock(),
            nodriver_kham_keyin_captcha_code=AsyncMock(), nodriver_kham_captcha=AsyncMock())
        async def snapshot(tab):
            return await tab.snapshot()
        async def close(tab):
            tab.dialog = ""
            return True
        async def submit(tab, script):
            tab.submits += 1
            return True
        self.patches = [patch.object(flow, "read_snapshot", side_effect=snapshot),
                        patch.object(flow, "close_dialog", side_effect=close),
                        patch.object(flow, "prepare_quantity", new=AsyncMock(return_value="ready")),
                        patch.object(flow, "_json", side_effect=submit),
                        patch.object(flow, "check_and_handle_pause", new=AsyncMock(return_value=False)),
                        patch.object(flow, "asyncio_sleep_with_pause_check", new=AsyncMock(return_value=False)),
                        patch.object(flow, "mark_bot_reload")]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    async def tick(self):
        return await flow.run(self.tab, self.tab.target.url, self.config, None, self.legacy)

    async def submit_ticket(self, performance, count):
        self.tab.target.url = BASE + f"UTK0205_.aspx?PRODUCT_ID=SHOW&PERFORMANCE_ID={performance}&PERFORMANCE_PRICE_AREA_ID=A"
        self.tab.quantity = count
        await self.tick()

    async def success(self):
        self.tab.dialog = "加入購物車完成，請於 10 分鐘內完成結帳！"
        await self.tick()

    async def test_two_days_end_in_verified_cart_and_remain_stopped(self):
        self.tab.target.url = BASE + "UTK0201_.aspx?PRODUCT_ID=SHOW"
        await self.tick()
        self.legacy.nodriver_kham_go_buy_redirect.assert_awaited_once()
        self.tab.target.url = DATE
        await self.tick()
        await self.submit_ticket("DAY1", 2)
        self.assertEqual(self.tab.submits, 1)
        await self.tick()
        self.assertEqual(self.tab.submits, 1, "pending requests must never submit twice")
        await self.success()
        self.assertEqual(self.tab.target.url, DATE)
        await self.tick()
        effective = self.legacy.nodriver_kham_product.await_args.args[2]
        self.assertEqual(effective["ticket_number"], 1)
        self.assertEqual(effective["date_auto_select"]["date_keyword"], '"10/04"')
        self.assertEqual(effective["area_auto_select"]["area_keyword"], '"B區"')
        self.assertFalse(effective["date_auto_fallback"])
        self.assertEqual(effective["_kham_completed_performances"], ["DAY1"])
        await self.submit_ticket("DAY2", 1)
        await self.success()
        self.assertEqual(self.tab.target.url, CART)
        self.tab.groups = [{"performance_id": "DAY1", "quantity": 2}, {"performance_id": "DAY2", "quantity": 1}]
        await self.tick()
        self.assertTrue(self.tab._kham_purchase_state.done)
        before = list(self.tab.visits)
        await self.tick()
        self.assertEqual(self.tab.visits, before)
        self.assertEqual(self.tab.submits, 2)
        self.assertEqual(self.config, config(), "runtime must not modify the user's queue/settings")

    async def test_failure_containing_add_to_cart_does_not_advance(self):
        await self.submit_ticket("DAY1", 2)
        self.tab.dialog = "加入購物車失敗，剩餘座位不足"
        await self.tick()
        self.assertEqual(self.tab._kham_purchase_state.index, 0)
        self.assertIn("UTK0204_", self.tab.target.url)
        flow.asyncio_sleep_with_pause_check.assert_awaited_with(0.25, unittest.mock.ANY)

    async def test_captcha_error_clears_and_retries_same_ticket(self):
        await self.submit_ticket("DAY1", 2)
        self.tab.dialog = "【驗證碼】輸入錯誤"
        await self.tick()
        self.assertFalse(self.tab._kham_purchase_state.pending)
        self.assertEqual(self.tab._kham_purchase_state.index, 0)
        self.legacy.nodriver_kham_keyin_captcha_code.assert_awaited_once_with(self.tab, "")

    async def test_submit_timeout_checks_cart_before_retrying(self):
        await self.submit_ticket("DAY1", 2)
        self.tab._kham_purchase_state.submitted_at = time.monotonic() - 100
        await self.tick()
        self.assertEqual(self.tab._kham_purchase_state.index, 0)
        self.assertEqual(self.tab.target.url, CART)
        self.assertTrue(self.tab._kham_purchase_state.pending)
        await self.tick()
        self.assertIn("UTK0204_", self.tab.target.url)

    async def test_timeout_with_successful_server_add_does_not_submit_again(self):
        await self.submit_ticket("DAY1", 2)
        self.tab._kham_purchase_state.submitted_at = time.monotonic() - 100
        self.tab.groups = [{"performance_id": "DAY1", "quantity": 2}]
        await self.tick()
        await self.tick()
        self.assertEqual(self.tab._kham_purchase_state.index, 1)
        self.assertEqual(self.tab.submits, 1)
        self.assertEqual(self.tab.target.url, DATE)

    async def test_cannot_cross_to_another_concert(self):
        await self.tick()
        self.tab.target.url = BASE + "UTK0205_.aspx?PRODUCT_ID=OTHER&PERFORMANCE_ID=OTHERDAY"
        await self.tick()
        self.assertEqual(self.tab.submits, 0)
        self.assertEqual(self.tab._kham_purchase_state.product_id, "SHOW")

    async def test_cart_navigation_without_dialog_requires_matching_performance_count(self):
        await self.submit_ticket("DAY1", 2)
        self.tab.target.url = CART
        self.tab.groups = [{"performance_id": "OTHER", "quantity": 9}]
        await self.tick()
        self.assertEqual(self.tab._kham_purchase_state.index, 0)
        await self.tick()
        await self.submit_ticket("DAY1", 2)
        self.tab.target.url = CART
        self.tab.groups = [{"performance_id": "DAY1", "quantity": 2}]
        await self.tick()
        self.assertEqual(self.tab._kham_purchase_state.index, 1)
        self.assertEqual(self.tab.target.url, DATE)

    async def test_expired_first_day_requeues_only_missing_day(self):
        await self.submit_ticket("DAY1", 2)
        await self.success()
        await self.tick()
        await self.submit_ticket("DAY2", 1)
        await self.success()
        self.tab.groups = [{"performance_id": "DAY2", "quantity": 1}]
        await self.tick()
        state = self.tab._kham_purchase_state
        self.assertFalse(state.done)
        self.assertEqual(state.index, 0)
        self.assertEqual(state.completed_performances, ["DAY2"])
        await self.tick()
        await self.submit_ticket("DAY1", 2)
        await self.success()
        self.assertEqual(state.index, 2, "already-present day2 must not be purchased again")

    async def test_settings_reload_does_not_reset_completed_queue(self):
        await self.submit_ticket("DAY1", 2)
        await self.success()
        self.config["kham"]["ticket_queue"].reverse()
        await self.tick()
        state = self.tab._kham_purchase_state
        self.assertEqual(state.index, 1)
        self.assertEqual(state.tickets[1]["date_keyword"], '"10/04"')

    async def test_partial_cart_only_purchases_deficit(self):
        await self.submit_ticket("DAY1", 2)
        self.tab.target.url = CART
        self.tab.groups = [{"performance_id": "DAY1", "quantity": 1}]
        await self.tick()
        state = self.tab._kham_purchase_state
        self.assertEqual(state.config_for_ticket(self.config)["ticket_number"], 1)
        # Follow the persisted retry destination before entering the seat page.
        await self.tick()
        await self.submit_ticket("DAY1", 1)
        self.tab.groups[0]["quantity"] = 2
        await self.success()
        self.assertEqual(state.completed[0]["quantity"], 2)
        self.assertNotIn(0, state.remaining)

    async def test_retry_navigation_failure_retains_destination_and_queue(self):
        await self.submit_ticket("DAY1", 2)
        self.tab.target.url = CART
        normal_get = self.tab.get
        self.tab.get = AsyncMock(side_effect=RuntimeError("temporary navigation failure"))
        await self.tick()
        state = self.tab._kham_purchase_state
        self.assertIn("UTK0204", state.destination)
        self.assertFalse(state.done)
        self.tab.get = normal_get
        await self.tick()
        self.assertIn("UTK0204", self.tab.target.url)
        self.assertFalse(state.done)

    async def test_missing_cart_table_reloads_without_losing_pending_state(self):
        await self.submit_ticket("DAY1", 2)
        self.tab.target.url = CART
        state = self.tab._kham_purchase_state
        state.page_url = CART
        state.page_entered_at = time.monotonic() - 20
        snapshot = await self.tab.snapshot()
        snapshot["cart_ready"] = False
        flow.read_snapshot.side_effect = None
        flow.read_snapshot.return_value = snapshot
        await self.tick()
        self.assertEqual(self.tab.visits[-1], CART)
        self.assertTrue(state.pending)
        self.assertFalse(state.done)

    async def test_purchase_limit_preserves_cart_and_halts_without_claiming_success(self):
        await self.submit_ticket("DAY1", 2)
        self.tab.dialog = "加入購物車失敗，超過每位會員購買上限4張"
        await self.tick()
        self.assertEqual(self.tab.target.url, CART)
        await self.tick()
        state = self.tab._kham_purchase_state
        self.assertTrue(state.halted)
        self.assertFalse(state.done)
        self.assertEqual(state.index, 0)
        before = list(self.tab.visits)
        await self.tick()
        self.assertEqual(self.tab.visits, before)

    async def test_manual_pause_returns_tab_from_adapter(self):
        from platforms import kham
        with patch.object(kham, "check_and_handle_pause", new=AsyncMock(return_value=True)):
            self.assertIs(await kham.nodriver_kham_main(self.tab, DATE, self.config, None), self.tab)

    async def test_wrong_quantity_and_incomplete_captcha_never_submit(self):
        self.tab.quantity = 0
        self.tab.target.url = BASE + "UTK0205_.aspx?PRODUCT_ID=SHOW&PERFORMANCE_ID=DAY1"
        await self.tick()
        self.assertEqual(self.tab.submits, 0)
        self.tab.quantity = 2
        self.tab.captcha = "12"
        await self.tick()
        self.assertEqual(self.tab.submits, 0)

    async def test_ocr_return_value_alone_does_not_count_as_filled_captcha(self):
        state = flow.PurchaseState(flow.ticket_plan(self.config))
        self.tab.captcha = "12"
        self.legacy.nodriver_kham_captcha.return_value = True
        self.assertFalse(await flow._fill_captcha(self.tab, self.config, object(), state, self.legacy))
        self.legacy.nodriver_kham_keyin_captcha_code.assert_awaited_once_with(self.tab, "")


class PlanTests(unittest.TestCase):
    def test_single_legacy_and_migration(self):
        import settings
        cfg = settings.migrate_config({"ticket_number": 3})
        self.assertEqual(cfg["kham"], {"ticket_queue": []})
        self.assertEqual(flow.ticket_plan(cfg)[0]["ticket_number"], 3)

    def test_invalid_queue_rejected(self):
        for value in (0, -1, 11, 1.5, True, "bad"):
            cfg = config()
            cfg["kham"]["ticket_queue"][0]["ticket_number"] = value
            with self.assertRaises(ValueError):
                flow.ticket_plan(cfg)
        cfg = config()
        cfg["kham"]["ticket_queue"][1]["date_keyword"] = ""
        with self.assertRaises(ValueError):
            flow.ticket_plan(cfg)
        cfg = config()
        cfg["kham"]["ticket_queue"][1]["date_keyword"] = cfg["kham"]["ticket_queue"][0]["date_keyword"]
        with self.assertRaises(ValueError):
            flow.ticket_plan(cfg)

    def test_dialog_classification(self):
        for text in ("加入購物車失敗", "無法成功加入購物車", "加入購物車未完成"):
            self.assertEqual(flow.classify_dialog(text), "retry")
        self.assertEqual(flow.classify_dialog("加入購物車完成，請於 10 分鐘內完成結帳！"), "success")
        self.assertEqual(flow.classify_dialog("【驗證碼】輸入錯誤"), "captcha")
        self.assertEqual(flow.classify_dialog("節目尚未啟售！"), "notice")
        self.assertEqual(flow.classify_dialog("加入購物車完成，請勿超過10分鐘，逾時失效"), "success")


if __name__ == "__main__":
    unittest.main()
