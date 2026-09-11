"""Exercise the real settings UI in isolated Chrome; all APIs stay in memory.

Run: conda run -n ticketH python -m unittest discover -s tests -p test_kham_settings_ui.py -v
Set KHAM_UI_SCREENSHOT_DIR to retain light/dark screenshots for visual review.
"""

import ast
import asyncio
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import unittest
from urllib.parse import urlsplit

import zendriver


ROOT = Path(__file__).resolve().parents[1]


def default_config():
    """Use production defaults without importing the server or reading secrets."""
    source = ast.parse((ROOT / "src/settings.py").read_text(encoding="utf-8-sig"))
    nodes = [node for node in source.body if (
        isinstance(node, ast.Assign)
        and all(isinstance(target, ast.Name) and target.id.startswith("CONST_")
                for target in node.targets)
    ) or (isinstance(node, ast.FunctionDef) and node.name == "get_default_config")]
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "defaults", "exec"), namespace)
    config = namespace["get_default_config"]()
    config["homepage"] = "https://kham.com.tw/application/UTK02/UTK0201_.aspx?PRODUCT_ID=test"
    config["ticket_number"] = 2
    config["date_auto_select"]["date_keyword"] = '"2026/10/03"'
    config["area_auto_select"]["area_keyword"] = '"A區;B區","C區"'
    return config


class MemorySettingsHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "src/www"), **kwargs)

    def log_message(self, *args):
        pass

    def json_response(self, data):
        payload = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/load":
            return self.json_response(self.server.config)
        if path == "/presets/list":
            return self.json_response({"presets": ["ui-test"]})
        if path == "/version":
            return self.json_response({"version": "KHAM offline UI test"})
        if path == "/status":
            return self.json_response({"status": False, "last_url": ""})
        if path.startswith("/api/") or path == "/question":
            return self.json_response({})
        if path == "/run":
            self.server.run_count += 1
            return self.json_response({"success": True})
        return super().do_GET()

    def do_POST(self):
        path = urlsplit(self.path).path
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        data = json.loads(body or b"{}")
        if path == "/save":
            self.server.config = data
            self.server.save_count += 1
        elif path == "/presets/get":
            return self.json_response({"success": True, "config": self.server.preset})
        elif path == "/presets/write_form":
            self.server.preset = data["config"]
            self.server.preset_write_count += 1
        return self.json_response({"success": True})


class KhamSettingsUITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), MemorySettingsHandler)
        cls.server.config = default_config()
        cls.server.preset = copy.deepcopy(cls.server.config)
        cls.server.save_count = cls.server.run_count = cls.server.preset_write_count = 0
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.profile = tempfile.TemporaryDirectory(prefix="kham-settings-ui-")
        cls.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(cls.loop)
        cls.browser = cls.loop.run_until_complete(zendriver.start(
            headless=True, user_data_dir=cls.profile.name,
            browser_args=[
                "--window-size=1400,1100",
                "--proxy-server=http://127.0.0.1:9",
                "--proxy-bypass-list=localhost;127.0.0.1",
                "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1",
                "--disable-background-networking", "--no-first-run",
            ],
        ))
        cls.tab = cls.loop.run_until_complete(cls.browser.get(
            f"http://127.0.0.1:{cls.server.server_port}/settings.html"))

    @classmethod
    def tearDownClass(cls):
        process = cls.browser._process
        cls.loop.run_until_complete(cls.browser.stop())
        if process:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream:
                    stream.close()
        cls.loop.close()
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=2)
        cls.profile.cleanup()

    async def evaluate(self, source):
        return await self.tab.evaluate(source)

    async def wait_for(self, expression):
        for _ in range(100):
            if await self.evaluate(expression):
                return
            await asyncio.sleep(0.05)
        details = await self.evaluate("JSON.stringify({url: location.href, title: document.title, settings: typeof settings, jquery: typeof $, text: document.body.innerText.slice(0, 250)})")
        self.fail("Timed out: " + expression + "\n" + str(details))

    def test_queue_sort_persist_validate_presets_and_legacy(self):
        self.loop.run_until_complete(self.exercise_ui())

    async def exercise_ui(self):
        await self.wait_for("typeof settings !== 'undefined' && !!settings && !!document.querySelector('.area-kw-slot')")
        self.assertTrue(await self.evaluate("!document.querySelector('#kham_ticket_queue_section').classList.contains('disappear')"))
        self.assertTrue(await self.evaluate("document.querySelector('#kham_first_ticket_down').disabled"))
        await self.evaluate("document.querySelector('#home-tab').click(); document.querySelector('#kham_add_next_ticket').click()")
        self.assertEqual(await self.evaluate("document.querySelectorAll('.kham-ticket-card').length"), 1)
        self.assertEqual(await self.evaluate("document.querySelector('#kham_ticket_1_area').value"), "A區;B區\nC區")

        # A blank next date must prevent both persistence and launching.
        self.assertFalse(await self.evaluate("save_changes_to_dict(true)"))
        await self.evaluate("maxbot_launch(); maxbot_save()")
        self.assertEqual(self.server.save_count, 0)
        self.assertEqual(self.server.run_count, 0)
        self.assertFalse(await self.evaluate("document.querySelector('#kham_ticket_queue_error').hidden"))
        await self.evaluate("document.querySelector('#kham_ticket_1_date').value=' 2026/10/03   '")
        self.assertFalse(await self.evaluate("save_changes_to_dict(true)"))
        self.assertIn("重複", await self.evaluate("document.querySelector('#kham_ticket_queue_error').textContent"))

        await self.evaluate("document.querySelector('#kham_ticket_1_number').value='3'; document.querySelector('#kham_ticket_1_date').value='2026/10/04'; document.querySelector('#kham_ticket_1_area').value='D區;E區\\nF區'; document.querySelector('#kham_add_next_ticket').click(); document.querySelector('#kham_ticket_2_number').value='1'; document.querySelector('#kham_ticket_2_date').value='2026/10/05'; document.querySelector('#kham_ticket_2_area').value='G區'")
        await self.evaluate("document.querySelector('#kham_ticket_1_number').closest('section').querySelector('[data-action=up]').click()")
        self.assertEqual(await self.evaluate("ticket_number.value"), "3")
        self.assertEqual(await self.evaluate("date_keyword.value"), "2026/10/04")
        self.assertEqual(await self.evaluate("collect_area_keyword_slots()"), '"D區;E區","F區"')
        self.assertEqual(await self.evaluate("document.querySelector('#kham_ticket_1_date').value"), "2026/10/03")
        self.assertTrue(await self.evaluate("document.querySelector('#kham_ticket_2_number').closest('section').querySelector('[data-action=down]').disabled"))

        await self.evaluate("document.querySelector('#kham_first_ticket_down').click(); document.querySelector('#kham_ticket_1_number').closest('section').querySelector('[data-action=down]').click(); maxbot_save()")
        await self.wait_for("document.querySelector('#run_btn_pressed_message').textContent.includes('已存檔')")
        self.assertEqual(self.server.save_count, 1)
        queue = self.server.config["kham"]["ticket_queue"]
        self.assertEqual([entry["date_keyword"] for entry in queue], ['"2026/10/03"', '"2026/10/05"', '"2026/10/04"'])
        self.assertEqual([entry["ticket_number"] for entry in queue], [2, 1, 3])
        self.assertEqual(self.server.config["ticket_number"], queue[0]["ticket_number"])
        self.assertEqual(self.server.config["area_auto_select"]["area_keyword"], queue[0]["area_keyword"])

        # Re-loading from the real form loader restores all three entries.
        await self.evaluate("load_settins_to_form(JSON.parse(JSON.stringify(settings)))")
        self.assertEqual(await self.evaluate("document.querySelectorAll('.kham-ticket-card').length"), 2)
        self.assertEqual(await self.evaluate("document.querySelector('#kham_ticket_2_area').value"), "D區;E區\nF區")

        # A long list from a subsequent card must survive moving into entry 1.
        await self.evaluate("window._originalQueue = collect_kham_ticket_queue(); document.querySelector('#kham_ticket_1_area').value=Array.from({length:12}, (_,i)=>'Area'+i).join('\\n'); move_kham_ticket(1, -1)")
        self.assertEqual(await self.evaluate("JSON.parse('[' + collect_area_keyword_slots() + ']').length"), 12)
        await self.evaluate("move_kham_ticket(0, 1)")
        self.assertEqual(await self.evaluate("document.querySelector('#kham_ticket_1_area').value.split('\\n').length"), 12)
        await self.evaluate("render_kham_ticket_queue(window._originalQueue)")

        screenshot_dir = os.environ.get("KHAM_UI_SCREENSHOT_DIR")
        if screenshot_dir:
            output = Path(screenshot_dir)
            output.mkdir(parents=True, exist_ok=True)
            for theme in ("light", "dark"):
                await self.evaluate(f"document.documentElement.setAttribute('data-bs-theme', '{theme}'); document.querySelector('#kham_ticket_queue_section').scrollIntoView()")
                await self.tab.save_screenshot(output / f"kham-ticket-queue-{theme}.png")
        await self.tab.send(zendriver.cdp.emulation.set_device_metrics_override(
            width=390, height=844, device_scale_factor=1, mobile=True))
        await self.evaluate("document.querySelector('#kham_ticket_queue_section').scrollIntoView()")
        self.assertTrue(await self.evaluate("Array.from(document.querySelectorAll('.kham-ticket-card, .kham-ticket-card button, .kham-ticket-card textarea')).every(el=>{const r=el.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth;})"))
        if screenshot_dir:
            await self.tab.save_screenshot(output / "kham-ticket-queue-mobile.png")
        await self.tab.send(zendriver.cdp.emulation.clear_device_metrics_override())

        # Editing a named preset loads a different queue and writes only its API.
        self.server.preset = copy.deepcopy(self.server.config)
        self.server.preset["kham"]["ticket_queue"][0]["date_keyword"] = '"2026/11/01"'
        self.server.preset["kham"]["ticket_queue"][1]["date_keyword"] = '"2026/11/02"'
        self.server.preset["kham"]["ticket_queue"] = self.server.preset["kham"]["ticket_queue"][:2]
        await self.evaluate("presets_dropdown.value='ui-test'; btn_edit_preset.click()")
        await self.wait_for("_editing_preset_name === 'ui-test'")
        self.assertEqual(await self.evaluate("date_keyword.value"), "2026/11/01")
        self.assertEqual(await self.evaluate("document.querySelectorAll('.kham-ticket-card').length"), 1)
        await self.evaluate("document.querySelector('#kham_ticket_1_date').value='2026/11/03'; btn_save_to_preset.click()")
        await self.wait_for("presets_status.textContent.includes('已存到')")
        self.assertEqual(self.server.preset_write_count, 1)
        self.assertEqual(self.server.preset["kham"]["ticket_queue"][1]["date_keyword"], '"2026/11/03"')
        self.assertEqual(self.server.save_count, 1)
        self.assertEqual(self.server.config["kham"]["ticket_queue"], queue)
        await self.evaluate("btn_exit_edit_preset.click()")
        await self.wait_for("date_keyword.value === '2026/10/03'")

        # KHAM queues must not replace another platform's common preferences.
        preserved_queue = json.dumps(queue, ensure_ascii=False)
        await self.evaluate("homepage.value='https://tixcraft.com'; updatePlatformFields(homepage.value); ticket_number.value='4'; date_keyword.value='other'; save_changes_to_dict(true)")
        self.assertTrue(await self.evaluate("document.querySelector('#kham_ticket_queue_section').classList.contains('disappear')"))
        self.assertEqual(await self.evaluate("JSON.stringify(settings.kham.ticket_queue)"), json.dumps(queue, ensure_ascii=False, separators=(",", ":")))
        await self.evaluate("load_settins_to_form(settings)")
        self.assertEqual(await self.evaluate("ticket_number.value"), "4")
        self.assertEqual(await self.evaluate("date_keyword.value"), "other")

        # Removing all subsequent entries restores the original single-ticket schema.
        await self.evaluate(f"settings.homepage='https://kham.com.tw'; settings.kham.ticket_queue={preserved_queue}; load_settins_to_form(settings); document.querySelector('[data-action=remove]').click(); document.querySelector('[data-action=remove]').click()")
        self.assertTrue(await self.evaluate("document.querySelector('#kham_first_ticket_down').disabled"))
        self.assertTrue(await self.evaluate("save_changes_to_dict(true)"))
        self.assertEqual(await self.evaluate("settings.kham.ticket_queue.length"), 0)
        await self.evaluate("delete settings.kham; load_settins_to_form(settings)")
        self.assertEqual(await self.evaluate("document.querySelectorAll('.kham-ticket-card').length"), 0)
        self.assertEqual(await self.evaluate("date_keyword.value"), "2026/10/03")


if __name__ == "__main__":
    unittest.main()
