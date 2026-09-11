"""Offline KHAM DOM regression checks using an isolated, headless browser.

Run in the ticketH environment: python -m unittest discover -s tests -p test_kham_browser.py -v
Trimmed repository fixtures are sanitized again before use. No ticket website is opened: the browser
uses a fresh temporary profile, a dead proxy, blocked DNS, and CDP offline mode.
"""

import asyncio
import functools
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
FIXTURES = ROOT / "tests" / "fixtures" / "kham"


class OfflineHTML(HTMLParser):
    """Keep DOM selectors and visibility, remove executable/resource content."""

    OMIT = {"script", "style", "iframe", "object", "embed", "noscript"}
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    RESOURCES = {"src", "srcset", "href", "action", "formaction", "poster", "background", "data", "ping"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.omitted = []

    def handle_starttag(self, tag, attrs):
        if self.omitted:
            if tag not in self.VOID:
                self.omitted.append(tag)
            return
        if tag in self.OMIT:
            if tag not in self.VOID:
                self.omitted.append(tag)
            return
        if tag in {"link", "base", "meta"}:
            return
        safe = []
        for name, value in attrs:
            if name in self.RESOURCES or name.startswith("on"):
                # Retain selector evidence without allowing original handlers to run.
                if name == "onclick":
                    safe.append(("data-original-onclick", value))
                continue
            if name == "style" and value and "url(" in value.lower():
                value = ";".join(part for part in value.split(";") if "url(" not in part.lower())
            safe.append((name, value))
        rendered = "".join(
            f' {name}' if value is None else f' {name}="{html.escape(value, quote=True)}"'
            for name, value in safe
        )
        self.parts.append(f"<{tag}{rendered}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.omitted:
            if tag in self.omitted:
                while self.omitted:
                    if self.omitted.pop() == tag:
                        break
            return
        if tag not in self.VOID and tag not in self.OMIT:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.omitted:
            self.parts.append(html.escape(data))

    @classmethod
    def sanitize(cls, source):
        parser = cls()
        parser.feed(source)
        parser.close()
        return "".join(parser.parts)


def browser_test(function):
    @functools.wraps(function)
    def run(self):
        return self.loop.run_until_complete(function(self))
    return run


class OfflineHTMLTests(unittest.TestCase):
    def test_saved_document_resources_and_scripts_are_removed(self):
        source = '<script>fetch("https://example.test")</script><iframe src="https://example.test"></iframe><img src="https://example.test" onerror="alert(1)"><button onclick="setType(1)">票別</button>'
        result = OfflineHTML.sanitize(source)
        self.assertNotIn("<script", result)
        self.assertNotIn("<iframe", result)
        self.assertNotIn(' src=', result)
        self.assertNotIn(' onerror=', result)
        self.assertNotIn(' onclick=', result)
        self.assertIn('data-original-onclick="setType(1)"', result)
        self.assertIn("票別", result)


class OfflinePurchaseTab:
    """Local route adapter; every selector, click and flow script runs in Chrome.

    Only URL navigation is virtual. The real tab stays on about:blank; calls to
    get load local synthetic DOM, and location.href reads use the virtual URL.
    This lets the actual KHAM controller and legacy date/area helpers execute
    their browser logic without opening a ticket site or sending a request.
    """

    BASE = "https://kham.com.tw/application/UTK02/"
    PRODUCT = "OFFLINE_CONCERT"
    MAIN = BASE + "UTK0201_.aspx?PRODUCT_ID=" + PRODUCT
    DATES = BASE + "UTK0201_00.aspx?PRODUCT_ID=" + PRODUCT
    CART = BASE + "UTK0206_.aspx"

    def __init__(self, case, drop_first_dialog=False):
        self.case = case
        self.raw = case.tab
        self.target = SimpleNamespace(url="about:blank")
        self.cart = []
        self.submissions = []
        self.visited = []
        self.ok_clicks = 0
        self.drop_first_dialog = drop_first_dialog

    def __getattr__(self, name):
        return getattr(self.raw, name)

    async def evaluate(self, expression, *args, **kwargs):
        expression = re.sub(r"(?<![\w.])location\.href", "window.__offline_url", expression)
        return await self.raw.evaluate(expression, *args, **kwargs)

    async def flush_events(self):
        events = await self.case.evaluate_json("""(() => {
            const events = {submission: window.__offline_submission || null, ok: window.__offline_ok || 0};
            window.__offline_submission = null;
            window.__offline_ok = 0;
            return events;
        })()""")
        if events["submission"]:
            receipt = events["submission"]
            self.submissions.append(receipt)
            self.cart.append(receipt.copy())
        self.ok_clicks += events["ok"]

    async def flush_navigation(self):
        await self.flush_events()
        destination = await self.raw.evaluate("window.__offline_next || ''")
        if destination:
            await self.get(destination)

    async def reload(self):
        await self.get(self.target.url)

    def route_button(self, label, destination):
        return '<button class="red" onclick="routeTo(\'' + html.escape(destination, quote=True) + '\');return false;">' + label + '</button>'

    async def get(self, url):
        await self.flush_events()
        self.target.url = url
        self.visited.append(url)
        page = urlsplit(url).path.rsplit("/", 1)[-1].lower()
        query = parse_qs(urlsplit(url).query)
        performance = query.get("PERFORMANCE_ID", [""])[0]
        area = query.get("PERFORMANCE_PRICE_AREA_ID", [""])[0]
        if page == "utk0201_.aspx":
            markup = self.route_button("我要購票", self.DATES).replace('<button ', '<button id="GO_BUY" ', 1)
        elif page == "utk0201_00.aspx":
            rows = []
            for day, pid in (("10/03", "DAY_ONE"), ("10/04", "DAY_TWO")):
                destination = self.BASE + "UTK0204_.aspx?PERFORMANCE_ID=" + pid + "&PRODUCT_ID=" + self.PRODUCT
                rows.append("<tr><td>2026/" + day + " 19:30</td><td>示範會場</td><td>4680、4280</td><td>" + self.route_button("立即訂購", destination) + "</td></tr>")
            markup = '<table class="eventTABLE"><tbody>' + "".join(rows) + '</tbody></table>'
        elif page == "utk0204_.aspx":
            rows = []
            for name, aid, stock in (("紅區", "RED", "100"), ("藍區", "BLUE", "7")):
                destination = self.BASE + "UTK0205_.aspx?PERFORMANCE_ID=" + performance + "&GROUP_ID=1&PERFORMANCE_PRICE_AREA_ID=" + aid
                rows.append('<tr class="status_tr filter-ready" onclick="routeTo(\'' + html.escape(destination, quote=True) + '\')"><td></td><td>' + name + '</td><td>4680</td><td>' + stock + '</td></tr>')
            markup = '<table id="salesTable"><tbody>' + "".join(rows) + '</tbody></table>'
        elif page == "utk0205_.aspx":
            markup = '''<button id="BUY_TYPE_2" class="red">電腦選位</button>
                <div class="ticket"><button class="green" onclick="setType('regular')">原價</button>
                <button class="red" onclick="setType('companion')">身障陪同票</button></div>
                <input id="AMOUNT" type="number" value="1" max="4"><input id="CHK" value="aB12">
                <button onclick="addShoppingCart();return false;">加入購物車</button>'''
        elif page == "utk0206_.aspx":
            rows = []
            for index, receipt in enumerate(self.cart):
                rows.append('<tr><td><input type="hidden" id="PERFORMANCE_ID" value="' + receipt["performance_id"] + '"><input type="hidden" id="PRODUCT_ID" value="' + self.PRODUCT + '"><input type="hidden" id="PKNO" value="ORDER_' + str(index) + '">測試演唱會</td><td>' + receipt["area"] + '</td><td><span id="ORDERQUANTITY">' + str(receipt["quantity"]) + '</span></td></tr>')
            markup = '<table class="eventTABLE step5 onlyStep5"><tbody><tr><th>名稱</th><th>票區</th><th>數量</th></tr>' + "".join(rows) + '<tr id="hide4col"><td>合計</td><td></td><td id="lbTotalQty">' + str(sum(row["quantity"] for row in self.cart)) + '</td></tr></tbody></table>'
        else:
            raise AssertionError("Unexpected offline route: " + url)
        await self.case.load_html(markup)
        await self.raw.evaluate("window.__offline_url = " + json.dumps(url) + "; window.routeTo = destination => { window.__offline_next = destination; };")
        if page == "utk0205_.aspx":
            receipt_fields = json.dumps({"performance_id": performance, "product_id": self.PRODUCT, "area": area})
            drop_dialog = self.drop_first_dialog and not self.submissions
            await self.raw.evaluate("""(() => {
                window.setType = value => {
                    window.selectedType = value;
                    document.querySelector('.ticket .green').classList.add('active');
                };
                window.addShoppingCart = () => {
                    window.__offline_submission = Object.assign(RECEIPT, {
                        quantity: Number(document.getElementById('AMOUNT').value),
                        ticket_type: window.selectedType || '',
                    });
                    if (DROP_DIALOG) return;
                    const dialog = document.createElement('div');
                    dialog.className = 'ui-dialog';
                    dialog.innerHTML = '<div id="dialog-message" class="ui-dialog-content">加入購物車完成，請於 10 分鐘內完成結帳！</div><div class="ui-dialog-buttonset"><button>Ok</button></div>';
                    dialog.querySelector('button').onclick = () => {
                        window.__offline_ok = (window.__offline_ok || 0) + 1;
                        dialog.style.display = 'none';
                    };
                    document.body.appendChild(dialog);
                };
            })()""".replace("RECEIPT", receipt_fields).replace("DROP_DIALOG", str(drop_dialog).lower()))
        return self


class KhamBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import zendriver
        from platforms import kham_flow

        cls.driver = zendriver
        cls.flow = kham_flow
        cls.loop = asyncio.new_event_loop()
        cls.profile = tempfile.TemporaryDirectory(prefix="ticket-hunter-offline-kham-")
        cls.browser = None
        try:
            cls.loop.run_until_complete(cls.start_browser())
        except Exception:
            if cls.browser is not None:
                cls.loop.run_until_complete(cls.browser.stop())
            cls.profile.cleanup()
            cls.loop.close()
            raise

    @classmethod
    async def start_browser(cls):
        cls.browser = await cls.driver.start(
            headless=True,
            user_data_dir=cls.profile.name,
            browser_args=[
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-sync",
                "--no-first-run",
                "--no-default-browser-check",
                "--proxy-server=http://127.0.0.1:9",
                "--proxy-bypass-list=<-loopback>",
                "--host-resolver-rules=MAP * ~NOTFOUND",
            ],
        )
        cls.tab = await cls.browser.get("about:blank")
        await cls.tab.send(cls.driver.cdp.network.enable())
        await cls.tab.send(cls.driver.cdp.network.set_blocked_ur_ls(["*"]))
        await cls.tab.send(cls.driver.cdp.network.emulate_network_conditions(
            offline=True, latency=0, download_throughput=0, upload_throughput=0,
        ))

    @classmethod
    def tearDownClass(cls):
        try:
            cls.loop.run_until_complete(cls.browser.stop())
        finally:
            cls.profile.cleanup()
            cls.loop.close()

    async def load_html(self, markup):
        await self.tab.get("about:blank")
        frame = await self.tab.send(self.driver.cdp.page.get_frame_tree())
        await self.tab.send(self.driver.cdp.page.set_document_content(frame.frame.id_, markup))

    async def load_fixture(self, name):
        await self.load_html(OfflineHTML.sanitize((FIXTURES / name).read_text(encoding="utf-8")))

    async def evaluate_json(self, expression):
        return json.loads(await self.tab.evaluate("JSON.stringify(" + expression + ")"))

    def config(self, number=2, exclude=""):
        return {
            "ticket_number": number,
            "keyword_exclude": exclude,
            "area_auto_select": {"enable": True, "area_keyword": "", "mode": "from top to bottom"},
            "advanced": {"disable_adjacent_seat": False, "verbose": False},
        }

    @browser_test
    async def test_saved_area_rows_keep_extension_classes_and_full_inventory(self):
        await self.load_fixture("3-area select.html")
        result = await self.evaluate_json("""(() => {
            const rows = Array.from(document.querySelectorAll('#salesTable tr.status_tr'));
            return {
                rows: rows.length,
                legacyRows: document.querySelectorAll('#salesTable tr[class="status_tr"]').length,
                hundred: rows.some(row => row.cells[3]?.textContent.trim() === '100'),
                unsafeResources: document.querySelectorAll('script,iframe,[src],[srcset],[onload],[onerror]').length,
            };
        })()""")
        self.assertGreater(result["rows"], 0)
        self.assertEqual(result["legacyRows"], 0)
        self.assertTrue(result["hundred"])
        self.assertEqual(result["unsafeResources"], 0)

    @browser_test
    async def test_saved_step_four_is_manual_seating_only(self):
        await self.load_fixture("4-seat select.html")
        result = await self.evaluate_json("""(() => ({
            types: document.querySelectorAll('.ticket button[data-original-onclick^="setType("]').length,
            captcha: !!document.querySelector('#CHK'),
            computer: !!document.querySelector('#BUY_TYPE_2'),
            quantity: !!document.querySelector('#AMOUNT'),
        }))()""")
        self.assertEqual(result["types"], 3)
        self.assertTrue(result["captcha"])
        self.assertFalse(result["computer"])
        self.assertFalse(result["quantity"])

    @browser_test
    async def test_real_success_dialog_closes_ok_and_ignores_hidden_dialog(self):
        await self.load_fixture("5-add to cart.html")
        snapshot = await self.flow.read_snapshot(self.tab)
        self.assertEqual(snapshot["dialog"], "加入購物車完成，請於 10 分鐘內完成結帳！")
        self.assertEqual(self.flow.classify_dialog(snapshot["dialog"]), "success")
        await self.tab.evaluate("""(() => {
            window.okClicked = 0;
            window.closeClicked = 0;
            const dialog = document.querySelector('.ui-dialog');
            dialog.querySelector('.ui-dialog-titlebar-close').onclick = () => { window.closeClicked++; };
            dialog.querySelector('.ui-dialog-buttonset button').onclick = () => {
                window.okClicked++;
                dialog.style.display = 'none';
            };
        })()""")
        self.assertTrue(await self.flow.close_dialog(self.tab))
        self.assertEqual(await self.tab.evaluate("window.okClicked"), 1)
        self.assertEqual(await self.tab.evaluate("window.closeClicked"), 0)
        self.assertTrue(await self.tab.evaluate("!!document.querySelector('.ui-dialog')"))
        self.assertEqual((await self.flow.read_snapshot(self.tab))["dialog"], "")
        self.assertFalse(await self.flow.close_dialog(self.tab))

    @browser_test
    async def test_real_presale_dialog_is_a_notice(self):
        await self.load_fixture("2026-EUNHYUK.html")
        # The downloaded product page retained an already dismissed presale
        # dialog. Ignore that stale node, then replay its visible state.
        self.assertEqual((await self.flow.read_snapshot(self.tab))["dialog"], "")
        await self.tab.evaluate("document.querySelector('.ui-dialog').style.display = 'block'")
        snapshot = await self.flow.read_snapshot(self.tab)
        self.assertEqual(snapshot["dialog"], "節目尚未啟售！")
        self.assertEqual(self.flow.classify_dialog(snapshot["dialog"]), "notice")

    @browser_test
    async def test_cart_snapshot_groups_real_ticket_rows_only(self):
        await self.load_fixture("6-cart page.html")
        groups = (await self.flow.read_snapshot(self.tab))["cart_groups"]
        self.assertEqual(len(groups), 1, "Cart header and total must not count as ticket orders")
        self.assertEqual(groups[0]["performance_id"], "P1D430L4")
        self.assertEqual(groups[0]["product_id"], "P1D3G65D")
        self.assertEqual(groups[0]["quantity"], 1)
        await self.tab.evaluate("""(() => {
            const first = document.querySelector('#ORDERQUANTITY').closest('tr');
            const next = first.cloneNode(true);
            next.querySelector('[id="PERFORMANCE_ID"]').value = 'SECOND_DAY';
            next.querySelector('[id="ORDERQUANTITY"]').textContent = '2';
            first.after(next);
        })()""")
        groups = (await self.flow.read_snapshot(self.tab))["cart_groups"]
        self.assertEqual(len(groups), 2)
        self.assertEqual({item["performance_id"]: item["quantity"] for item in groups}, {"P1D430L4": 1, "SECOND_DAY": 2})

    @browser_test
    async def test_empty_cart_with_header_and_total_is_empty(self):
        await self.load_fixture("6-cart page.html")
        await self.tab.evaluate("document.querySelector('#ORDERQUANTITY').closest('tr').remove()")
        self.assertEqual((await self.flow.read_snapshot(self.tab))["cart_groups"], [])

    @browser_test
    async def test_computer_ticket_type_is_clicked_and_default_one_is_overwritten(self):
        await self.load_html('''<div class="ticket">
            <button class="green" onclick="setType('regular')">原價</button>
            <button class="red" onclick="setType('companion')">身障陪同票</button>
            </div><input id="AMOUNT" type="number" value="1" max="4">''')
        await self.tab.evaluate("window.lastType = ''; window.setType = value => { window.lastType = value; }")
        self.assertEqual(await self.flow.prepare_quantity(self.tab, self.config(2)), "ready")
        self.assertEqual(await self.tab.evaluate("window.lastType"), "regular", "Red is a ticket color, not evidence that the ticket type was selected")
        self.assertEqual((await self.flow.read_snapshot(self.tab))["quantity"], 2)

    @browser_test
    async def test_multiple_ticket_type_counts_are_cleared_with_shared_exclusion(self):
        await self.load_html('''<div><label>原價<input id="AMOUNT" type="number" key="REG" value="1" max="4"></label>
            <input id="REG_NAME" type="hidden" value="原價"></div>
            <div><label>身障票<input id="AMOUNT" type="number" key="ACC" value="2" max="4"></label>
            <input id="ACC_NAME" type="hidden" value="身障票"></div>''')
        await self.tab.evaluate("""window.opera1 = (key, increase) => {
            const input = document.querySelector('input[key="' + key + '"]');
            input.value = String(Number(input.value) + (increase ? 1 : -1));
        }""")
        self.assertEqual(await self.flow.prepare_quantity(self.tab, self.config(3, '"身障"')), "ready")
        self.assertEqual(await self.tab.evaluate("document.querySelector('input[key=REG]').value"), "3")
        self.assertEqual(await self.tab.evaluate("document.querySelector('input[key=ACC]').value"), "0")
        self.assertEqual((await self.flow.read_snapshot(self.tab))["quantity"], 3)

    @browser_test
    async def test_ticket_type_exclusions_support_and_groups_and_semicolon_alternatives(self):
        for exclude in ('身障 陪同;遮蔽', '["身障","陪同"],"遮蔽"'):
            with self.subTest(exclude=exclude):
                await self.load_html('''<div class="ticket">
                    <button onclick="setType('companion')">身障　陪同票</button>
                    <button onclick="setType('obstructed')">遮蔽席</button>
                    <button onclick="setType('normal')">原價票</button>
                    </div><input id="AMOUNT" type="number" value="0" max="4">''')
                await self.tab.evaluate("window.selectedType = ''; window.setType = value => { window.selectedType = value; }")
                self.assertEqual(await self.flow.prepare_quantity(self.tab, self.config(2, exclude)), "ready")
                self.assertEqual(await self.tab.evaluate("window.selectedType"), "normal")
                self.assertEqual((await self.flow.read_snapshot(self.tab))["quantity"], 2)

    @browser_test
    async def test_select_quantity_and_inventory_limit(self):
        await self.load_html('<label>原價<select id="AMOUNT"><option value="0">0</option><option value="1">1</option><option value="2">2</option></select></label>')
        self.assertEqual(await self.flow.prepare_quantity(self.tab, self.config(2)), "ready")
        self.assertEqual((await self.flow.read_snapshot(self.tab))["quantity"], 2)
        self.assertEqual(await self.flow.prepare_quantity(self.tab, self.config(3)), "unavailable")
        await self.load_html('<label>原價<input id="AMOUNT" type="number" value="0" max="1"></label>')
        self.assertEqual(await self.flow.prepare_quantity(self.tab, self.config(2)), "unavailable")

    @browser_test
    async def test_switch_to_computer_seating_before_quantity(self):
        await self.load_html('<button id="BUY_TYPE_2" class="gray">電腦選位</button><input id="AMOUNT" type="number" value="0" max="4">')
        await self.tab.evaluate("document.querySelector('#BUY_TYPE_2').onclick = event => { event.currentTarget.className = 'red'; }")
        self.assertEqual(await self.flow.prepare_quantity(self.tab, self.config(2)), "switched")
        self.assertEqual((await self.flow.read_snapshot(self.tab))["quantity"], 0)
        self.assertEqual(await self.flow.prepare_quantity(self.tab, self.config(2)), "ready")

    @browser_test
    async def test_native_computer_radio_uses_checked_state_and_disabled_mode_blocks_submit(self):
        await self.load_html('<input id="BUY_TYPE_1" type="radio" name="mode" checked><input id="BUY_TYPE_2" type="radio" name="mode" class="red"><input id="AMOUNT" type="number" value="0">')
        self.assertEqual(await self.flow.prepare_quantity(self.tab, self.config(2)), "switched")
        self.assertTrue(await self.tab.evaluate("document.getElementById('BUY_TYPE_2').checked"))
        self.assertEqual(await self.flow.prepare_quantity(self.tab, self.config(2)), "ready")
        await self.load_html('<button id="BUY_TYPE_2" class="gray" disabled>電腦選位</button><input id="AMOUNT" type="number" value="0">')
        self.assertNotEqual(await self.flow.prepare_quantity(self.tab, self.config(2)), "ready", "An unavailable computer mode cannot be reported ready merely because a quantity field exists")

    @browser_test
    async def test_unavailable_excluded_type_and_manual_page_do_not_submit(self):
        await self.load_html('<div class="ticket"><button onclick="setType(1)">身障票</button></div><input id="AMOUNT" type="number" value="0">')
        self.assertEqual(await self.flow.prepare_quantity(self.tab, self.config(2, '"身障"')), "unavailable")
        self.assertEqual((await self.flow.read_snapshot(self.tab))["quantity"], 0)
        await self.load_fixture("4-seat select.html")
        self.assertEqual(await self.flow.prepare_quantity(self.tab, self.config(2)), "waiting")

    @browser_test
    async def test_real_manual_seat_snapshot_counts_only_selected_seats(self):
        await self.load_fixture("4-seat select.html")
        self.assertEqual((await self.flow.read_snapshot(self.tab))["selected_seats"], 0)
        await self.load_fixture("5-add to cart.html")
        snapshot = await self.flow.read_snapshot(self.tab)
        self.assertEqual(snapshot["selected_seats"], 1)
        self.assertTrue(snapshot["has_seats"])
        self.assertFalse(snapshot["has_quantity"])
        self.assertEqual(await self.tab.evaluate("document.querySelectorAll('#TBL td.SeatAddCart').length"), 4)

    @browser_test
    async def test_saved_manual_flow_selects_exact_count_before_one_submission(self):
        from platforms import kham as legacy

        tab = OfflinePurchaseTab(self)
        tab.target.url = tab.BASE + "UTK0205_.aspx?PERFORMANCE_ID=DAY_ONE&GROUP_ID=29&PERFORMANCE_PRICE_AREA_ID=RED"
        await self.load_fixture("4-seat select.html")
        await self.tab.evaluate("window.__offline_url = " + json.dumps(tab.target.url))
        await self.tab.evaluate("""(() => {
            window.manualSubmissions = [];
            window.setType = () => {
                document.querySelector('.ticket .green').classList.add('active');
            };
            window.addShoppingCart = () => {
                window.manualSubmissions.push(document.querySelectorAll('#TBL td.selected').length);
            };
            document.querySelectorAll('[data-original-onclick]').forEach(button => {
                const handler = button.getAttribute('data-original-onclick');
                if (handler.startsWith('setType(') || handler.startsWith('addShoppingCart(')) {
                    button.setAttribute('onclick', handler);
                }
            });
            document.querySelectorAll('#TBL td.empty').forEach(seat => {
                seat.onclick = () => { seat.classList.toggle('selected'); };
            });
            document.getElementById('CHK').value = 'aB12';
        })()""")
        config = self.config(2, '"身障"')
        config.update({
            "homepage": tab.MAIN,
            "date_auto_select": {"enable": True, "date_keyword": '"10/03"', "mode": "from top to bottom"},
            "ocr_captcha": {"enable": False},
            "kham": {"ticket_queue": []},
        })
        self.assertTrue(await self.flow.run(tab, tab.target.url, config, None, legacy))
        self.assertEqual((await self.flow.read_snapshot(tab))["selected_seats"], 2)
        self.assertEqual(await self.evaluate_json("window.manualSubmissions"), [2])
        self.assertTrue(tab._kham_purchase_state.pending)
        await self.flow.run(tab, tab.target.url, config, None, legacy)
        self.assertEqual(await self.evaluate_json("window.manualSubmissions"), [2])

    async def run_offline_purchase(self, drop_first_dialog=False):
        from platforms import kham as legacy

        tab = OfflinePurchaseTab(self, drop_first_dialog=drop_first_dialog)
        config = self.config(2, '"身障"')
        config.update({
            "homepage": tab.MAIN,
            "date_auto_select": {"enable": True, "date_keyword": '"10/03"', "mode": "from top to bottom"},
            "date_auto_fallback": False,
            "area_auto_fallback": False,
            "ocr_captcha": {"enable": False, "force_submit": False},
            "tixcraft": {"auto_reload_coming_soon_page": True},
            "kham": {"ticket_queue": [
                {"ticket_number": 2, "date_keyword": '"10/03"', "area_keyword": '"紅區"'},
                {"ticket_number": 1, "date_keyword": '"10/04"', "area_keyword": '"藍區"'},
            ]},
        })
        config["advanced"].update({
            "auto_reload_page_interval": 0,
            "post_submit_reload_guard_seconds": 5,
            "play_sound": {"order": False},
        })
        await tab.get(tab.MAIN)
        expired = False
        for _ in range(30):
            self.assertTrue(await self.flow.run(tab, tab.target.url, config, None, legacy))
            await tab.flush_navigation()
            state = getattr(tab, "_kham_purchase_state", None)
            if state and state.done:
                break
            if drop_first_dialog and state and state.pending and len(tab.submissions) == 1 and not expired:
                # Advance only the recorded submission time; no real sleep or
                # core controller/snapshot/quantity/dialog mocks are needed.
                state.submitted_at -= 70
                expired = True
        self.assertIsNotNone(state)
        self.assertTrue(state.done, "The controller did not finish the two-day purchase in 30 iterations; route=" + tab.target.url)
        self.assertEqual(tab.target.url, tab.CART)
        self.assertEqual(len(tab.submissions), 2, "A completed or uncertain submission must never be blindly submitted again")
        self.assertEqual([(item["performance_id"], item["quantity"], item["area"], item["ticket_type"]) for item in tab.submissions], [
            ("DAY_ONE", 2, "RED", "regular"),
            ("DAY_TWO", 1, "BLUE", "regular"),
        ])
        snapshot = await self.flow.read_snapshot(tab)
        self.assertEqual(len(snapshot["cart_groups"]), 2)
        self.assertEqual({item["performance_id"]: item["quantity"] for item in snapshot["cart_groups"]}, {"DAY_ONE": 2, "DAY_TWO": 1})
        self.assertEqual(tab.ok_clicks, 1 if drop_first_dialog else 2)
        visits = list(tab.visited)
        for _ in range(3):
            await self.flow.run(tab, tab.target.url, config, None, legacy)
            await tab.flush_navigation()
        self.assertEqual(tab.visited, visits)
        self.assertEqual(len(tab.submissions), 2)

    @browser_test
    async def test_two_day_end_to_end_keeps_both_orders_and_stops(self):
        await self.run_offline_purchase()

    @browser_test
    async def test_lost_success_response_checks_cart_before_retrying(self):
        await self.run_offline_purchase(drop_first_dialog=True)


if __name__ == "__main__":
    unittest.main()
