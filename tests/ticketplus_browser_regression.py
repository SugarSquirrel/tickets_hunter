"""Offline Chrome purchase regression and optional before/after timing.

python tests/ticketplus_browser_regression.py --chrome "C:/.../chrome.exe"
Add --baseline PATH/TO/ticketplus.py to compare the original keyword loop.
All HTTP/HTTPS requests are blocked. Only temporary local HTML is loaded.
"""
import argparse
import asyncio
import importlib.util
import json
import re
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import zendriver as zd
import util
from platforms import ticketplus as current
from settings import get_default_config


PAGE_JS = r"""
const cfg = __CFG__;
const stallUntil = performance.now() + (cfg.stallMs || 0);
window.isEnquene = false;
window.result = null;
window.refreshes = 0;
window.refreshTimes = [];
window.badClicks = 0;
const zones = ['A區', 'B區', 'C區'].map((name, i) => ({name, count: 0, idx: i}));
const page = {tickets: zones, serialNumber: '', guarantee: false, isPending: false,
              isRefresh: false, session: {transactionValidType: 'serial'}, $children: []};
Object.defineProperties(page, {
    totalTicket: {get: () => zones.reduce((s, z) => s + z.count, 0)},
    hasSerial: {get: () => page.totalTicket > 0},
    canNextStep: {get: () => page.totalTicket > 0 && page.guarantee && !!page.serialNumber}
});
const app = document.querySelector('#app');
app.__vue__ = {$children: [page]};
app.innerHTML = '<div class="seats-area">' + zones.map(z =>
    '<div class="v-expansion-panel" data-idx="' + z.idx + '">' +
    '<button class="v-expansion-panel-header">' + z.name + ' NT.5,980</button></div>'
).join('') + '</div><div class="exclusive-code"><input type="tel"></div>' +
    '<input type="checkbox"><div class="order-footer"><button class="nextBtn disabledBtn">下一步</button></div>' +
    '<button class="float-btn">更新票數</button>';
function body(z) {
    if (cfg.locked === z.name) return '<span>本階段不開放</span>';
    return '<div class="count-button"><button><i class="mdi-minus"></i></button>' +
           '<span class="count">' + z.count + '</span><button><i class="mdi-plus"></i></button></div>';
}
if (cfg.row) {
    app.querySelector('.seats-area').outerHTML = zones.map(z =>
        '<div class="row py-1 py-md-4" data-idx="' + z.idx + '">' +
        '<div class="font-weight-medium">' + z.name + ' NT.5,980</div>' + body(z) + '</div>'
    ).join('');
}
function sync() {
    const next = app.querySelector('.nextBtn');
    next.disabled = !page.canNextStep;
    next.classList.toggle('disabledBtn', !page.canNextStep);
    app.querySelectorAll('[data-idx] .count').forEach(el => {
        el.textContent = zones[+el.closest('[data-idx]').dataset.idx].count;
    });
}
app.querySelector('.exclusive-code input').addEventListener('input', e => {
    page.serialNumber = e.target.value; sync();
});
app.querySelector('input[type=checkbox]').addEventListener('change', e => {
    page.guarantee = e.target.checked; sync();
});
app.addEventListener('click', e => {
    const header = e.target.closest('.v-expansion-panel-header');
    if (header) {
        const panel = header.parentNode;
        panel.classList.add('v-expansion-panel--active');
        if (!panel.querySelector('.v-expansion-panel-content')) setTimeout(() => {
            panel.insertAdjacentHTML('beforeend', '<div class="v-expansion-panel-content"><div>' +
                body(zones[+panel.dataset.idx]) + '</div></div>');
        }, 15);
    }
    const plus = e.target.closest('.mdi-plus'), minus = e.target.closest('.mdi-minus');
    if (plus || minus) {
        if (page.isRefresh) { window.badClicks++; return; }
        const z = zones[+(plus || minus).closest('[data-idx]').dataset.idx];
        if (plus && cfg.stalled === z.name && performance.now() < stallUntil) return;
        z.count = Math.max(0, z.count + (plus ? 1 : -1));
        Promise.resolve().then(sync);
    }
    if (e.target.closest('.float-btn')) {
        window.refreshes++;
        window.refreshTimes.push(performance.now());
        page.isRefresh = true;
        setTimeout(() => { page.isRefresh = false; window.readyAt = performance.now(); sync(); }, cfg.refreshMs || 500);
    }
    if (e.target.closest('.nextBtn') && page.canNextStep) {
        window.result = {zone: zones.find(z => z.count).name, count: page.totalTicket,
                         serial: page.serialNumber, at: performance.now()};
        window.isEnquene = true;
    }
});
sync();
if (cfg.preopen) app.querySelector('.v-expansion-panel-header').click();
"""


def config(keywords):
    cfg = get_default_config()
    cfg["ticket_number"] = 2
    cfg["area_auto_select"]["area_keyword"] = util.format_config_keyword_for_json(";".join(keywords))
    cfg["area_auto_select"]["mode"] = "from top to bottom"
    cfg["area_auto_fallback"] = False
    cfg["advanced"].update(action_speed_multiplier=0, auto_reload_page_interval=-1,
                           verbose=False, discount_code="", play_sound={"ticket": False, "order": False})
    cfg["contact"]["credit_card_prefix"] = "412345"
    return cfg


async def run(args):
    util.set_instance_id("ticketplus-browser-test")
    modules = [("new", current)]
    if args.baseline:
        spec = importlib.util.spec_from_file_location("ticketplus_baseline", args.baseline)
        baseline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(baseline)
        modules.insert(0, ("baseline", baseline))

    with tempfile.TemporaryDirectory(prefix="ticketplus-test-") as work, \
         patch.object(util, "get_instance_state_path", lambda name: str(Path(work) / name)):
        browser = await zd.start(headless=True, browser_executable_path=args.chrome,
                                 user_data_dir=str(Path(work) / "profile"))
        try:
            tab = browser.main_tab
            await tab.send(zd.cdp.network.enable())
            await tab.send(zd.cdp.network.set_blocked_ur_ls(urls=["http://*", "https://*"]))

            async def load(module, **options):
                module._state.clear()
                module._state.update(fail_list=[], is_ticket_assigned=False)
                html = '<html><body><div id="app"></div><script>' + PAGE_JS.replace('__CFG__', json.dumps(options)) + '</script></body></html>'
                path = Path(work) / "order.html"
                path.write_text(html, encoding="utf-8")
                await tab.get(path.as_uri())
                await asyncio.sleep(0.05)

            for label, module in modules:
                for name, keywords, options, expected in [
                    ("priority", ["missing", "B區", "A區"], {}, "B區"),
                    ("locked-first", ["A區", "C區"], {"locked": "A區"}, "C區"),
                    ("AND-and-price", ["C區 5980"], {}, "C區"),
                    ("rows-priority", ["missing", "C區", "B區"], {"row": True}, "C區"),
                    *([("retry-scope", ["C區"], {"preopen": True, "stalled": "C區", "stallMs": 500}, "C區")]
                      if label == "new" else []),
                ]:
                    await load(module, **options)
                    await module.nodriver_ticketplus_order(tab, config(keywords), None, None)
                    result = json.loads(await tab.evaluate("JSON.stringify(window.result)"))
                    assert result and result["zone"] == expected and result["count"] == 2 and result["serial"] == "412345", (label, name, result)
                    # Re-entry must not add another two tickets or double-submit.
                    await module.nodriver_ticketplus_order(tab, config(keywords), None, None)
                    state = json.loads(await tab.evaluate("JSON.stringify({count:document.querySelector('#app').__vue__.$children[0].totalTicket,result:window.result})"))
                    assert state["count"] == 2 and state["result"] == result, state
                    print(f"PASS {label} {name}: selected, filled code, pressed next, safe re-entry", flush=True)

                await load(module)
                cfg = config([])
                keywords = ["missing" + str(i) for i in range(9)]
                calls = 0
                original = tab.evaluate

                async def counted(*a, **kw):
                    nonlocal calls
                    calls += 1
                    return await original(*a, **kw)

                tab.evaluate = counted
                started = time.perf_counter()
                try:
                    if label == "baseline":
                        for keyword in keywords:
                            assert not await module.nodriver_ticketplus_unified_select(tab, cfg, keyword)
                    else:
                        assert not await module.nodriver_ticketplus_unified_select(tab, cfg, keywords)
                finally:
                    tab.evaluate = original
                print(f"BENCH {label}: 9 misses {(time.perf_counter()-started)*1000:.1f}ms, {calls} evaluate calls", flush=True)
                if label == "new":
                    assert calls == 3, calls

            # The real refresh gate must hold through a slow response, keep the loop
            # responsive, and select/submit as soon as the page declares itself ready.
            await load(current, refreshMs=700)
            debug = util.create_debug_logger(config([]))
            assert await current._ticketplus_click_refresh_button(tab, debug)
            started = time.perf_counter()
            checks = 0
            while not await current._ticketplus_refresh_is_ready(tab, debug):
                checks += 1
                assert time.perf_counter() - started < 2
                assert await current._ticketplus_click_refresh_button(tab, debug)
                await asyncio.sleep(0.03)
            await current.nodriver_ticketplus_order(tab, config(["B區"]), None, None)
            state = json.loads(await tab.evaluate("JSON.stringify({refreshes, badClicks, result:window.result, readyAt:window.readyAt})"))
            assert checks > 0 and state["refreshes"] == 1 and state["badClicks"] == 0, state
            assert state["result"] and state["result"]["at"] >= state["readyAt"], state
            print("PASS slow refresh: one refresh, no stale clicks, code filled and next pressed after completion", flush=True)

            # This compatibility fixture has no inventory loader. The button
            # fallback must still respect a minimum interval without overlapping.
            await load(current, refreshMs=80)
            cfg = config(["missing"])
            cfg["advanced"]["auto_reload_page_interval"] = 0.3
            original = tab.evaluate

            async def slow_scan(expression, *a, **kw):
                if "const keywords =" in expression:
                    await asyncio.sleep(0.2)
                return await original(expression, *a, **kw)

            tab.evaluate = slow_scan
            started = time.perf_counter()
            try:
                while True:
                    await current.nodriver_ticketplus_order(tab, cfg, None, None)
                    stamps = json.loads(await original("JSON.stringify(window.refreshTimes)"))
                    if len(stamps) >= 3:
                        break
                    assert time.perf_counter() - started < 5, stamps
                    await asyncio.sleep(0.01)
            finally:
                tab.evaluate = original
            gaps = [b - a for a, b in zip(stamps, stamps[1:])]
            assert min(gaps) >= 280, gaps
            print(f"PASS button fallback: minimum 300ms interval, measured gaps {[round(g) for g in gaps]}ms", flush=True)

            await load(current)
            current._state.clear()
            await current.nodriver_ticketplus_main(
                tab, "https://ticketplus.com.tw/order/event/session", config(["B區"]), None, None)
            result = json.loads(await tab.evaluate("JSON.stringify(window.result)"))
            assert result and result["zone"] == "B區" and result["count"] == 2, result
            print("PASS platform entry: startup, Vue readiness, popup check, selection, code and next", flush=True)

            await load(current)
            clock = SimpleNamespace(time=lambda: 0, monotonic=time.monotonic)
            real_evaluate = current._ticketplus_evaluate

            async def expired_selection(tab, expression, **kwargs):
                if "const keywords =" in expression:
                    expression = re.sub(r"const selectionDeadline = \d+;", "const selectionDeadline = 0;", expression)
                return await real_evaluate(tab, expression, **kwargs)

            with patch.object(current, "_ticketplus_evaluate", expired_selection):
                assert not await current.nodriver_ticketplus_unified_select(tab, config(["B區"]), ["B區"])
            with patch.object(current, "time", clock):
                assert await real_evaluate(tab, "(function(){window.lateAction=true; return true;})()") is None
            assert await tab.evaluate("window.lateAction !== true")
            count = await tab.evaluate("page.totalTicket")
            assert count == 0, count
            assert await current.nodriver_ticketplus_unified_select(tab, config(["B區"]), ["B區"])
            await tab.evaluate("page.serialNumber='412345'; page.guarantee=true; sync();")
            with patch.object(current, "time", clock):
                assert not await current.nodriver_ticketplus_click_next_button_unified(tab, config(["B區"]))
            assert json.loads(await tab.evaluate("JSON.stringify(window.result)")) is None
            print("PASS expired actions: stale selection/submit scripts cannot click later", flush=True)

            activity = Path(work) / "activity.html"
            activity.write_text('''<html><body><div id="app"><div id="buyTicket">
              <div class="sesstion-item">O'Reilly 2026
              <button class="nextBtn" onclick="window.dateClicked=true">立即購買</button>
              </div></div></div></body></html>''', encoding="utf-8")
            await tab.get(activity.as_uri())
            current._state.clear()
            cfg = config([])
            cfg["date_auto_select"]["date_keyword"] = json.dumps("O'Reilly")
            cfg["tixcraft"]["auto_reload_coming_soon_page"] = False
            assert await current.nodriver_ticketplus_date_auto_select(tab, cfg)
            assert await tab.evaluate("window.dateClicked === true")
            print("PASS date fallback: apostrophe keyword selects the intended purchase button", flush=True)
        finally:
            await browser.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chrome", required=True)
    parser.add_argument("--baseline")
    asyncio.run(run(parser.parse_args()))
