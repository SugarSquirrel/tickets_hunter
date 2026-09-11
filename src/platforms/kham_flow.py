"""KHAM purchase queue. Only a confirmed cart addition completes a ticket.

The legacy KHAM family adapter is still used for login, date/area selection
and OCR. This controller owns KHAM navigation and computer-seat submission.
"""

import copy
import json
import re
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import util
from nodriver_common import (
    asyncio_sleep_with_pause_check, check_and_handle_pause, mark_bot_reload,
    play_sound_while_ordering,
)


def ticket_plan(config):
    section = config.get("kham", {})
    if not isinstance(section, dict):
        raise ValueError("寬宏設定格式錯誤")
    queue = section.get("ticket_queue", [])
    if not queue:
        queue = [{"ticket_number": config["ticket_number"],
                  "date_keyword": config["date_auto_select"]["date_keyword"],
                  "area_keyword": config["area_auto_select"]["area_keyword"]}]
    if not isinstance(queue, list):
        raise ValueError("寬宏購票順序必須是清單")
    result = []
    seen_dates = set()
    for i, ticket in enumerate(queue):
        if not isinstance(ticket, dict):
            raise ValueError(f"寬宏第 {i + 1} 筆購票設定格式錯誤")
        count = ticket.get("ticket_number")
        if isinstance(count, bool) or not str(count).isdigit() or not 1 <= int(count) <= 10:
            raise ValueError(f"寬宏第 {i + 1} 筆票數須為 1～10")
        item = {"ticket_number": int(count)}
        for key in ("date_keyword", "area_keyword"):
            value = ticket.get(key, "")
            if not isinstance(value, str):
                raise ValueError(f"寬宏第 {i + 1} 筆關鍵字須為文字")
            item[key] = value.strip()
        if len(queue) > 1 and not item["date_keyword"]:
            raise ValueError(f"寬宏第 {i + 1} 筆須填寫日期關鍵字")
        date = re.sub(r"\s+", " ", item["date_keyword"]).casefold()
        if len(queue) > 1 and date in seen_dates:
            raise ValueError(f"寬宏第 {i + 1} 筆日期關鍵字重複；接續購票僅限不同日期場次")
        seen_dates.add(date)
        result.append(item)
    return result


@dataclass
class PurchaseState:
    tickets: list
    product_id: str = ""
    index: int = 0
    date_url: str = ""
    area_url: str = ""
    performance_id: str = ""
    completed_performances: list = field(default_factory=list)
    completed: dict = field(default_factory=dict)
    remaining: dict = field(default_factory=dict)
    pending: bool = False
    submitted_at: float = 0.0
    success_seen: bool = False
    destination: str = ""
    done: bool = False
    halted: bool = False
    stop_reason: str = ""
    message: str = ""
    last_ocr: float = 0.0
    page_url: str = ""
    page_entered_at: float = 0.0

    def config_for_ticket(self, config):
        effective = copy.deepcopy(config)
        item = self.tickets[min(self.index, len(self.tickets) - 1)]
        effective["ticket_number"] = self.remaining.get(self.index, item["ticket_number"])
        effective["date_auto_select"]["date_keyword"] = item["date_keyword"]
        effective["area_auto_select"]["area_keyword"] = item["area_keyword"]
        effective["_kham_completed_performances"] = list(self.completed_performances)
        # Each queue item is a specific day. Never substitute another day.
        if len(self.tickets) > 1:
            effective["date_auto_fallback"] = False
        return effective


def classify_dialog(text):
    compact = re.sub(r"\s+", "", text or "")
    if "驗證碼" in compact and any(k in compact for k in ("錯誤", "不正確", "重新", "輸入")):
        return "captcha"
    failed = any(k in compact for k in ("失敗", "無法", "未完成", "不成功", "尚未成功", "未加入"))
    if not failed and any(k in compact for k in ("加入購物車完成", "成功加入購物車", "已加入購物車")):
        return "success"
    if "限購" in compact or ("上限" in compact and any(k in compact for k in ("購買", "購票", "訂購", "張數", "票數", "會員"))):
        return "limit"
    if failed:
        return "retry"
    if any(k in compact for k in ("不足", "售完", "售罄", "已被", "已售", "逾時", "超過", "上限", "錯誤")):
        return "retry"
    if any(k in compact for k in ("尚未", "未啟售", "未開賣", "實名制")):
        return "notice"
    return "unknown"


async def _json(tab, script):
    # Returning JSON text avoids zendriver's nested CDP RemoteObject format.
    result = await tab.evaluate("JSON.stringify((() => {" + script + "})())")
    return json.loads(result) if isinstance(result, str) else result


VISIBLE_JS = """
    const visible = el => !!el && !!el.getClientRects().length &&
        getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none';
"""


async def read_snapshot(tab):
    return await _json(tab, VISIBLE_JS + """
        const dialogs = Array.from(document.querySelectorAll('.ui-dialog')).filter(visible);
        const dialog = dialogs.find(el => el.querySelector('#dialog-message, .ui-dialog-content'));
        const content = dialog && dialog.querySelector('#dialog-message, .ui-dialog-content');
        const amounts = Array.from(document.querySelectorAll('input#AMOUNT, select#AMOUNT, select[id*="AMOUNT_DDL"]')).filter(visible);
        const table = document.querySelector('table.eventTABLE.step5.onlyStep5');
        return {
            url: location.href, ready: document.readyState !== 'loading',
            dialog: content ? content.textContent.trim() : '',
            captcha: (document.querySelector('#CHK') || {}).value || '',
            quantity: amounts.reduce((sum, el) => sum + (parseInt(el.value, 10) || 0), 0),
            has_quantity: amounts.length > 0,
            has_types: !!document.querySelector('.ticket button[onclick*="setType"]'),
            has_seats: !!document.querySelector('#TBL'),
            selected_seats: document.querySelectorAll('#TBL td.selected').length,
            busy: !!(window.jQuery && window.jQuery.active > 0),
            login: ['LOGIN_ID', 'LOGIN_PWD', 'ACCOUNT'].some(id => visible(document.getElementById(id))),
            cart_text: table ? table.innerText : '',
            cart_ready: !!table,
            cart_groups: table ? Array.from(table.querySelectorAll('tr')).flatMap(tr => {
                const performance = tr.querySelector('input[id="PERFORMANCE_ID"]');
                const quantity = tr.querySelector('span[id="ORDERQUANTITY"]');
                if (!performance || !quantity) return [];
                return [{performance_id: performance.value,
                    product_id: (tr.querySelector('input[id="PRODUCT_ID"]') || {}).value || '',
                    pkno: (tr.querySelector('input[id="PKNO"]') || {}).value || '',
                    quantity: parseInt(quantity.textContent, 10) || 0, text: tr.innerText.trim()}];
            }) : []
        };
    """)


async def close_dialog(tab):
    return await _json(tab, VISIBLE_JS + """
        const dialogs = Array.from(document.querySelectorAll('.ui-dialog')).filter(visible);
        for (const dialog of dialogs) {
            const button = Array.from(dialog.querySelectorAll('.ui-dialog-buttonset button'))
                .find(el => visible(el) && !el.disabled && /^(ok|確定|確認|好)$/i.test(el.textContent.trim()));
            if (button) { button.click(); return true; }
        }
        return false;
    """)


async def prepare_quantity(tab, config):
    """Select a non-excluded ticket type, then verify the exact requested count.

    UTK0205 can be manual-only (the saved example), while sale-day pages
    may expose the computer-seat toggle or numeric/select quantity controls.
    Never submit the manual map as if it were a computer-seat quantity form.
    """
    raw_exclude = config.get("keyword_exclude", "")
    excluded = util.parse_keyword_string_to_array(raw_exclude)
    if raw_exclude.strip() and (not excluded or any(not isinstance(item, (str, list)) for item in excluded)):
        excluded = [raw_exclude]
    result = await _json(tab, VISIBLE_JS + r"""
        const target = TARGET_COUNT;
        const excludes = EXCLUDES;
        const matches = (group, text) => {
            if (Array.isArray(group)) return group.length > 0 && group.every(part => matches(part, text));
            return String(group).split(';').filter(part => part.trim()).some(part =>
                part.trim().split(/\s+/).every(word => text.includes(word.replace(/　/g, ''))));
        };
        const excluded = text => excludes.some(group => matches(group, text.replace(/　/g, '')));
        const auto = document.getElementById('BUY_TYPE_2');
        if (auto && visible(auto)) {
            const native = auto.matches('input[type="radio"], input[type="checkbox"]');
            const active = native ? auto.checked : (auto.classList.contains('red') || auto.getAttribute('aria-pressed') === 'true');
            if (!active) {
                if (auto.disabled) return 'blocked';
                auto.click(); return 'switched';
            }
        }
        const buttons = Array.from(document.querySelectorAll('.ticket button[onclick*="setType"], button[onclick^="setType("]'));
        const candidates = buttons.filter(el => visible(el) && !el.disabled && !excluded(el.textContent));
        if (buttons.length && !candidates.length) return 'unavailable';
        if (candidates.length) {
            const selected = candidates.find(el => el.classList.contains('active'));
            // setType updates the site's currType, even on default-auto pages.
            if (!selected) candidates[0].click();
        }
        const inputs = Array.from(document.querySelectorAll('input#AMOUNT, select#AMOUNT, select[id*="AMOUNT_DDL"]')).filter(visible);
        if (!inputs.length) return 'waiting';
        const eligible = inputs.filter(el => {
            const key = el.getAttribute('key');
            const name = key && document.getElementById(key + '_NAME');
            const type = candidates.find(button => button.classList.contains('active')) || candidates[0];
            const row = el.closest('tr');
            const label = name ? name.value : (inputs.length === 1 && type ? type.textContent : (row ? row.textContent : ''));
            return !el.disabled && !excluded(label);
        });
        if (!eligible.length) return 'unavailable';
        const chosen = eligible[0];
        const assign = (input, number) => {
            if ((parseInt(input.value, 10) || 0) === number) return true;
            if (input.tagName === 'SELECT') {
                if (!Array.from(input.options).some(opt => !opt.disabled && opt.value === String(number))) return false;
            } else if (number > 0 && input.max && number > Number(input.max)) return false;
            const key = input.getAttribute('key');
            if (key && typeof opera1 === 'function') {
                for (let i = 0; i < 20 && (parseInt(input.value, 10) || 0) !== number; i++) {
                    const before = parseInt(input.value, 10) || 0;
                    opera1(key, before < number);
                    if ((parseInt(input.value, 10) || 0) === before) break;
                }
            } else {
                input.value = String(number);
                input.dispatchEvent(new Event('input', {bubbles: true}));
                input.dispatchEvent(new Event('change', {bubbles: true}));
            }
            return (parseInt(input.value, 10) || 0) === number;
        };
        // Clear other ticket types so a stale/prefilled count cannot add extras.
        for (const input of inputs) {
            if (input !== chosen && (parseInt(input.value, 10) || 0) && !assign(input, 0)) return 'unavailable';
        }
        if (!assign(chosen, target)) return 'unavailable';
        const total = inputs.reduce((sum, el) => sum + (parseInt(el.value, 10) || 0), 0);
        return total === target ? 'ready' : 'unavailable';
    """.replace("TARGET_COUNT", str(int(config["ticket_number"]))).replace("EXCLUDES", json.dumps(excluded, ensure_ascii=False)))
    return result


def _page(url):
    return urlsplit(url).path.rsplit("/", 1)[-1].lower()


def _query(url):
    return {key.lower(): values[0] for key, values in parse_qs(urlsplit(url).query).items()}


def _page_url(url, filename, query=""):
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rsplit("/", 1)[0] + "/" + filename, query, ""))


def _remember_pages(state, url):
    query = _query(url)
    product = query.get("product_id")
    if product and not state.product_id:
        state.product_id = product
    if _page(url) == "utk0201_00.aspx":
        state.date_url = url
    elif product and not state.date_url:
        state.date_url = _page_url(url, "UTK0201_00.aspx", urlencode({"PRODUCT_ID": product}))
    if query.get("performance_id"):
        state.performance_id = query["performance_id"]
        if _page(url) == "utk0204_.aspx" and not query.get("performance_price_area_id"):
            state.area_url = url
        elif not state.area_url:
            values = {"PERFORMANCE_ID": state.performance_id}
            if product:
                values["PRODUCT_ID"] = product
            state.area_url = _page_url(url, "UTK0204_.aspx", urlencode(values))


def _say(state, message):
    if state.message != message:
        print("[KHAM] " + message)
        state.message = message


async def _retry(tab, state, config, *, date=False):
    interval = max(0.0, float(config.get("advanced", {}).get("auto_reload_page_interval", 1.0) or 0))
    await asyncio_sleep_with_pause_check(interval, config)
    if await check_and_handle_pause(config):
        return
    state.pending = False
    state.success_seen = False
    destination = state.date_url if date else (state.area_url or state.date_url)
    mark_bot_reload()
    if destination:
        state.destination = destination
        await tab.get(destination)
    else:
        await tab.reload()


async def _advance(tab, state, url):
    if not state.success_seen or not state.pending:
        return
    state.pending = False
    state.success_seen = False
    state.completed[state.index] = {"performance_id": state.performance_id,
                                    "quantity": state.tickets[state.index]["ticket_number"]}
    state.remaining.pop(state.index, None)
    if state.performance_id:
        state.completed_performances.append(state.performance_id)
    state.index = next((i for i in range(len(state.tickets)) if i not in state.completed), len(state.tickets))
    state.area_url = ""
    state.performance_id = ""
    state.last_ocr = 0.0
    _say(state, f"已確認 {len(state.completed)}/{len(state.tickets)} 筆加入購物車。")
    state.destination = (state.date_url if state.index < len(state.tickets)
                         else _page_url(url, "UTK0206_.aspx"))
    if state.destination:
        await tab.get(state.destination)


async def _fill_captcha(tab, config, ocr, state, legacy):
    value = await tab.evaluate("(document.querySelector('#CHK') || {}).value || ''")
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9]{4}", value.strip()):
        return True
    if config.get("ocr_captcha", {}).get("enable") and ocr:
        cooldown = float(config.get("advanced", {}).get("ocr_retry_cooldown", 0.3) or 0)
        if time.monotonic() - state.last_ocr < max(0.1, cooldown):
            return False
        state.last_ocr = time.monotonic()
        # The legacy OCR filler preserves any nonempty text, including the
        # placeholder or an invalid previous answer. Clear it before retrying.
        await legacy.nodriver_kham_keyin_captcha_code(tab, "")
        await legacy.nodriver_kham_captcha(tab, config, ocr, _page(tab.target.url)[:7].upper())
        value = await tab.evaluate("(document.querySelector('#CHK') || {}).value || ''")
        return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9]{4}", value.strip()))
    _say(state, "等待輸入驗證碼，輸入完成後會繼續加入購物車。")
    return False


def cart_quantity(groups, performance):
    return sum(group.get("quantity", 0) for group in groups if group.get("performance_id") == performance)


def cart_contains(groups, receipt):
    performance = receipt.get("performance_id")
    return bool(performance) and cart_quantity(groups, performance) >= receipt["quantity"]


async def run(tab, url, config, ocr, legacy):
    """Return True for handled KHAM purchase pages; False delegates to login."""
    page = _page(url)
    if not page.startswith(("utk0201", "utk0202", "utk0204", "utk0205", "utk0206")):
        return False
    state = getattr(tab, "_kham_purchase_state", None)
    if state is None:
        try:
            state = PurchaseState(ticket_plan(config))
        except ValueError as exc:
            print(f"[KHAM] 設定錯誤：{exc}")
            return True
        tab._kham_purchase_state = state
    if state.done or state.halted or await check_and_handle_pause(config):
        return True
    # Freeze the queue for this run so a settings hot reload cannot reset progress.
    effective = state.config_for_ticket(config)
    try:
        snap = await read_snapshot(tab)
        if not snap or not snap.get("ready"):
            return True
        url = snap["url"]
        page = _page(url)
        if state.page_url != url:
            state.page_url = url
            state.page_entered_at = time.monotonic()
        if state.destination:
            if url.lower() != state.destination.lower():
                await tab.get(state.destination)
                return True
            state.destination = ""
        product = _query(url).get("product_id")
        if state.product_id and product and product != state.product_id:
            _say(state, "目前頁面不是本次演唱會；請返回原演唱會，或重新啟動機器人開始新的購票順序。")
            return True
        _remember_pages(state, url)
        dialog = snap.get("dialog", "")
        if dialog:
            kind = classify_dialog(dialog)
            if kind == "success" and state.pending:
                state.success_seen = True
                if await close_dialog(tab):
                    await _advance(tab, state, url)
                return True
            if await close_dialog(tab):
                if kind == "limit":
                    state.pending = False
                    state.stop_reason = "網站限制購票數量，已停止接續購票並保留購物車：" + dialog
                    state.destination = _page_url(url, "UTK0206_.aspx")
                    _say(state, state.stop_reason)
                    await tab.get(state.destination)
                elif kind == "captcha":
                    state.pending = False
                    await legacy.nodriver_kham_keyin_captcha_code(tab, "")
                    await tab.evaluate("(() => {const img=document.querySelector('#chk_pic'); if(img) img.click();})()")
                elif kind == "retry":
                    _say(state, f"尚未入車，依設定間隔重新選區：{dialog}")
                    await _retry(tab, state, effective)
                elif state.pending:
                    _say(state, "收到未確認的送出結果，先核對購物車。")
                    state.destination = _page_url(url, "UTK0206_.aspx")
                    await tab.get(state.destination)
                elif kind == "notice" and any(word in dialog for word in ("尚未", "未啟售", "未開賣")):
                    await _retry(tab, state, effective, date=True)
            return True
        if state.success_seen and state.pending:
            await _advance(tab, state, url)
            return True
        if page == "utk0206_.aspx":
            if state.stop_reason:
                state.halted = True
                _say(state, state.stop_reason)
                return True
            if not snap.get("cart_ready", bool(snap.get("cart_groups"))):
                _say(state, "等待購物車資料載入後再確認票券。")
                if time.monotonic() - state.page_entered_at > 10:
                    state.page_entered_at = time.monotonic()
                    mark_bot_reload()
                    await tab.reload()
                return True
            groups = snap.get("cart_groups", [])
            if state.index == len(state.tickets):
                missing = [i for i, receipt in state.completed.items() if not cart_contains(groups, receipt)]
                if missing:
                    for i in missing:
                        receipt = state.completed[i]
                        state.remaining[i] = receipt["quantity"] - cart_quantity(groups, receipt["performance_id"])
                        del state.completed[i]
                    state.completed_performances = [r["performance_id"] for r in state.completed.values()]
                    state.index = min(missing)
                    _say(state, "購物車有票券已逾時或數量不足，依原設定補買缺少的場次。")
                    await _retry(tab, state, config, date=True)
                else:
                    state.done = True
                    _say(state, f"全部 {len(state.tickets)} 筆已核對在購物車，機器人停止購票，請完成結帳。")
                    if effective.get("advanced", {}).get("play_sound", {}).get("order"):
                        play_sound_while_ordering(effective)
            elif state.pending:
                # Some server responses navigate without showing the modal.
                # Require the submitted performance and count in actual cart rows.
                receipt = {"performance_id": state.performance_id, "quantity": state.tickets[state.index]["ticket_number"]}
                if cart_contains(groups, receipt):
                    state.success_seen = True
                    await _advance(tab, state, url)
                else:
                    state.remaining[state.index] = receipt["quantity"] - cart_quantity(groups, state.performance_id)
                    _say(state, "購物車未出現本次票券，依設定間隔重新選區。")
                    await _retry(tab, state, effective)
            else:
                _say(state, "目前在購物車，保留票券並停止購票。")
                state.done = True
            return True
        if state.pending:
            guard = float(effective.get("advanced", {}).get("post_submit_reload_guard_seconds", 12) or 12)
            elapsed = time.monotonic() - state.submitted_at
            if elapsed < max(5, guard) or (snap.get("busy") and elapsed < max(60, guard)):
                return True
            _say(state, "送出後未收到結果，先核對購物車，避免重複加入票券。")
            state.destination = _page_url(url, "UTK0206_.aspx")
            await tab.get(state.destination)
            return True
        if page in ("utk0201_.aspx", "utk0201_040.aspx"):
            await legacy.nodriver_kham_go_buy_redirect(tab, urlsplit(url).netloc)
            if time.monotonic() - state.page_entered_at > 10:
                await _retry(tab, state, effective, date=True)
                state.page_entered_at = time.monotonic()
            return True
        if page in ("utk0201_00.aspx", "utk0201_041.aspx"):
            if effective["date_auto_select"]["enable"]:
                state.date_url = url
                await legacy.nodriver_kham_product(tab, urlsplit(url).netloc, effective)
            return True
        if page == "utk0204_.aspx" and not snap.get("has_quantity") and not snap.get("has_types") and not snap.get("has_seats"):
            if effective["area_auto_select"]["enable"]:
                await legacy.nodriver_kham_performance(tab, effective, ocr, urlsplit(url).netloc, "UTK0204")
            return True
        if snap.get("login"):
            _say(state, "此頁需要會員登入；登入完成後會自動繼續。")
            return True
        quantity = await prepare_quantity(tab, effective)
        if quantity == "switched":
            return True
        if quantity == "unavailable":
            await _retry(tab, state, effective)
            return True
        manual = quantity == "waiting" and snap.get("has_seats")
        if manual:
            selected = await _json(tab, "return document.querySelectorAll('#TBL td.selected').length;")
            if selected != effective["ticket_number"]:
                if selected:
                    await _json(tab, "document.querySelectorAll('#TBL td.selected').forEach(el => el.click()); return true;")
                await legacy.nodriver_kham_seat_auto_select(tab, effective)
                selected = await _json(tab, "return document.querySelectorAll('#TBL td.selected').length;")
            if selected != effective["ticket_number"]:
                await _retry(tab, state, effective)
                return True
            quantity = "ready"
        if quantity != "ready":
            _say(state, "等待票數欄位載入，持續無法載入時會回到票區重試。")
            if time.monotonic() - state.page_entered_at > 10:
                await _retry(tab, state, effective)
                state.page_entered_at = time.monotonic()
            return True
        if effective.get("advanced", {}).get("disable_adjacent_seat"):
            await legacy.nodriver_kham_allow_not_adjacent_seat(tab, effective)
        if not await _fill_captcha(tab, effective, ocr, state, legacy):
            return True
        if await check_and_handle_pause(config):
            return True
        # Re-read after change handlers/OCR. Never submit an unverified count.
        check = await read_snapshot(tab)
        verified_count = check.get("selected_seats") if manual else check.get("quantity")
        if check.get("dialog") or check.get("busy") or verified_count != effective["ticket_number"]:
            return True
        state.pending = True
        state.submitted_at = time.monotonic()
        clicked = await _json(tab, VISIBLE_JS + """
            const button = Array.from(document.querySelectorAll('button[onclick*="addShoppingCart"], #addcart button'))
                .find(el => visible(el) && !el.disabled);
            if (!button) return false;
            button.click(); return true;
        """)
        if not clicked:
            state.pending = False
        return True
    except Exception as exc:
        # Navigation destroys execution contexts. Keep pending state so the next
        # main-loop iteration handles the response instead of submitting twice.
        util.create_debug_logger(config).log(f"[KHAM] Page changed or temporarily unavailable: {exc}")
        return True
