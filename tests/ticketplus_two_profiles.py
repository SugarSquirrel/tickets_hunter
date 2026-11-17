"""Two independent profiles through the real bot main loop, on local HTML only.

python tests/ticketplus_two_profiles.py --chrome C:/.../chrome.exe
Optional --module PATH/TO/ticketplus.py measures an older implementation.
"""
import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ticketplus_browser_regression import PAGE_JS, config

INVENTORY_JS = r"""
window.inventoryTimes = [];
window.inventoryOverlap = 0;
window.inventoryActive = false;
app.addEventListener('click', e => {
    if (e.target.closest('.mdi-plus') && window.ticketAt == null) window.ticketAt = performance.now();
}, true);
app.addEventListener('input', e => {
    if (e.target.closest('.exclusive-code')) window.codeAt = performance.now();
}, true);
const widget = {loadingData: false, $children: []};
app.__vue__.$children.push(widget);
page.loadingData = false;
zones.forEach(z => { z.loadingStatusFinished = true; z.status = 'onsale'; });
page.productInit = function() {
    window.inventoryTimes.push(performance.now());
    if (window.inventoryActive) window.inventoryOverlap++;
    window.inventoryActive = true;
    page.loadingData = true;
    zones.forEach(z => { z.loadingStatusFinished = false; });
    return new Promise(resolve => setTimeout(() => {
        page.loadingData = false;
        zones.forEach(z => { z.loadingStatusFinished = true; });
        page.tickets = zones.slice();
        if (__COMBINED__) page.session = Object.assign({}, page.session);
        window.inventoryActive = false;
        if (window.inventoryTimes.length >= 6) {
            zones[1].name = 'Wanted';
            app.querySelector('[data-idx="1"] .v-expansion-panel-header').textContent = 'Wanted NT.5,980';
        }
        resolve();
    }, __INVENTORY_MS__));
};
page.updateInfo = function() {
    window.infoCalls = (window.infoCalls || 0) + 1;
    widget.loadingData = true;
    return new Promise(resolve => setTimeout(() => { widget.loadingData = false; resolve(); }, 1800));
};
// Mirror TicketPlus: inventory completes first; refreshEnd follows 500ms
// later and starts other metadata work. Those are not inventory readiness.
app.addEventListener('click', function(e) {
    if (!e.target.closest('.float-btn')) return;
    e.stopImmediatePropagation();
    if (page.isRefresh) return;
    page.isRefresh = true;
    page.productInit(true).then(() => setTimeout(() => {
        page.isRefresh = false;
        page.updateInfo();
    }, 500));
}, true);
"""


class Args(SimpleNamespace):
    def __getattr__(self, name):
        return None


async def worker(args):
    import builtins
    import zendriver as zd
    import util
    import nodriver_tixcraft as app

    original_print = builtins.print
    work = Path(args.work)
    app_root = work.parent / "app"
    (app_root / "profiles").mkdir(parents=True, exist_ok=True)
    cfg = config(["Wanted"])
    cfg["advanced"].update(auto_reload_page_interval=0.5, headless=True, show_timestamp=False)
    cfg["ocr_captcha"]["enable"] = True
    cfg["homepage"] = "https://ticketplus.com.tw/order/local-event/local-session"
    cfg["advanced"]["discount_code"] = "TESTCODE123" if args.worker == "account-a" else "PROFILEB123"
    cfg["contact"]["credit_card_prefix"] = ""
    cfg_path = app_root / "settings.json" if args.worker == "account-a" else app_root / "profiles" / "ticketplus.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    util.get_app_root = lambda: str(app_root)
    app.get_extension_config = lambda *a: zd.Config(
        headless=True, browser_executable_path=args.chrome, user_data_dir=str(work / "chrome"))
    app.nodriver_overwrite_prefs = lambda *a: None
    ocr_initializations = []

    def unexpected_ocr(*a):
        ocr_initializations.append(True)
        raise AssertionError("TicketPlus must not initialize OCR")

    app.create_ocr_for_platform = unexpected_ocr
    if args.module:
        spec = importlib.util.spec_from_file_location("ticketplus_control", args.module)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        app.nodriver_ticketplus_main = module.nodriver_ticketplus_main

    original_start = app.uc.start
    original_url = app.nodriver_current_url
    holder = {}

    async def start(conf):
        browser = await original_start(conf)
        tab = browser.main_tab
        await tab.send(zd.cdp.network.enable())
        await tab.send(zd.cdp.network.set_blocked_ur_ls(urls=["http://*", "https://*"]))
        holder["browser"] = browser
        return browser

    async def mapped_url(tab, cfg):
        url, quit_requested = await original_url(tab, cfg)
        if url.startswith("file:"):
            url = "https://ticketplus.com.tw/order/local-event/local-session"
        return url, quit_requested

    async def local_homepage(browser, cfg):
        tab = browser.main_tab
        await tab.get((work / "order.html").as_uri())
        return tab

    app.uc.start = start
    app.nodriver_current_url = mapped_url
    app.nodriver_goto_homepage = local_homepage
    app.write_last_url_to_file = lambda *a: None
    task = asyncio.create_task(app.main(Args(input=str(cfg_path))))
    deadline = time.monotonic() + 30
    state = None
    try:
        while time.monotonic() < deadline and not task.done():
            await asyncio.sleep(0.1)
            browser = holder.get("browser")
            if not browser:
                continue
            try:
                raw = await asyncio.wait_for(browser.main_tab.evaluate('''JSON.stringify({
                    times:window.inventoryTimes, overlap:window.inventoryOverlap,
                    result:window.result, ticketAt:window.ticketAt, codeAt:window.codeAt, infoCalls:window.infoCalls || 0,
                    slowWidget:typeof widget !== 'undefined' && widget.loadingData
                })'''), 2)
                state = json.loads(raw)
            except Exception:
                continue
            if state.get("result"):
                break
        gaps = [b-a for a, b in zip((state or {}).get("times", []), (state or {}).get("times", [])[1:])]
        result = {"profile": args.worker, "instance": util.get_instance_id(), "gaps_ms": [round(g,1) for g in gaps],
                  "mean_ms": round(statistics.mean(gaps),1) if gaps else None,
                  "overlap": (state or {}).get("overlap"), "submitted": (state or {}).get("result"),
                  "ocr_initializations": len(ocr_initializations),
                  "metadata_requests": (state or {}).get("infoCalls", 0),
                  "code_after_selection_ms": round(state["codeAt"]-state["ticketAt"],1)
                    if state and state.get("codeAt") is not None and state.get("ticketAt") is not None else None}
        (work / "result.json").write_text(json.dumps(result), encoding="utf-8")
        (Path(util.get_instance_state_path("MAXBOT_INT28_QUIT.txt"))).touch()
        await asyncio.wait_for(task, 12)
    finally:
        if not task.done():
            task.cancel()
        if holder.get("browser"):
            await holder["browser"].stop()
        builtins.print = original_print


def parent(args):
    with tempfile.TemporaryDirectory(prefix="ticketplus-two-profiles-") as temp:
        children = []
        for name in ("account-a", "account-b"):
            work = Path(temp) / name
            work.mkdir()
            fixture = INVENTORY_JS.replace("__INVENTORY_MS__", str(args.inventory_ms)).replace("__COMBINED__", "true" if args.combined else "false")
            js = PAGE_JS.replace("__CFG__", "{}") + "\n" + fixture
            (work / "order.html").write_text(
                '<html><meta charset="utf-8"><body><div id="app"></div><script>' + js + '</script></body></html>', encoding="utf-8")
            log = (work / "worker.log").open("w", encoding="utf-8")
            cmd = [sys.executable, "-u", "-X", "utf8", str(Path(__file__).resolve()),
                   "--worker", name, "--work", str(work), "--chrome", args.chrome]
            if args.module:
                cmd += ["--module", str(Path(args.module).resolve())]
            children.append((subprocess.Popen(cmd, stdout=log, stderr=log), work, log))
        results = []
        for proc, work, log in children:
            try:
                proc.wait(timeout=55)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(timeout=10)
            log.close()
        for proc, work, log in children:
            result_path = work / "result.json"
            if not result_path.exists() or proc.returncode:
                print((work / "worker.log").read_text(encoding="utf-8", errors="replace")[-3000:])
                raise AssertionError(f"{work.name}: process exit {proc.returncode}")
            result = json.loads(result_path.read_text())
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
        for result in results:
            assert len(result["gaps_ms"]) >= 5, result
            assert result["overlap"] == 0, result
            assert result["submitted"] and result["submitted"]["count"] == 2, result
            expected_code = "TESTCODE123" if result["profile"] == "account-a" else "PROFILEB123"
            expected_instance = "default" if result["profile"] == "account-a" else "ticketplus"
            assert result["submitted"]["serial"] == expected_code and result["instance"] == expected_instance, result
            if not args.module:
                if args.combined:
                    assert result["metadata_requests"] == 0, result
                assert result["ocr_initializations"] == 0, result
                assert result["code_after_selection_ms"] is not None and 0 <= result["code_after_selection_ms"] <= 400, result
                assert 480 <= min(result["gaps_ms"]), result
                assert result["mean_ms"] <= max(650, args.inventory_ms + 250), result
                assert max(result["gaps_ms"]) <= max(800, args.inventory_ms + 400), result
                if args.inventory_ms > 500:
                    assert min(result["gaps_ms"]) >= args.inventory_ms - 10, result
        print("PASS two profiles: real main loops, independent refreshes, no overlaps, both reached next", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chrome", required=True)
    parser.add_argument("--module")
    parser.add_argument("--inventory-ms", type=int, default=120)
    parser.add_argument("--combined", action="store_true", help="current site loader also updates campaign/session metadata")
    parser.add_argument("--worker")
    parser.add_argument("--work")
    args = parser.parse_args()
    if args.worker:
        asyncio.run(worker(args))
    else:
        parent(args)
