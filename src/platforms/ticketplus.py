#!/usr/bin/env python3
#encoding=utf-8
"""platforms/ticketplus.py -- TicketPlus platform (ticketplus.com.tw)."""

import asyncio
import json
import random
import time
import traceback

from zendriver import cdp

import util
from nodriver_common import (
    check_and_handle_pause,
    check_and_handle_quit,
    evaluate_with_pause_check,
    play_sound_while_ordering,
    send_discord_notification,
    send_telegram_notification,
    sleep_with_pause_check,
)


__all__ = [
    "nodriver_ticketplus_detect_layout_style",
    "nodriver_ticketplus_account_sign_in",
    "nodriver_ticketplus_is_signin",
    "nodriver_ticketplus_account_auto_fill",
    "nodriver_ticketplus_date_auto_select",
    "nodriver_ticketplus_unified_select",
    "nodriver_ticketplus_click_next_button_unified",
    "nodriver_ticketplus_ticket_agree",
    "nodriver_ticketplus_accept_realname_card",
    "nodriver_ticketplus_accept_other_activity",
    "nodriver_ticketplus_accept_order_fail",
    "nodriver_ticketplus_check_queue_status",
    "nodriver_ticketplus_confirm",
    "nodriver_ticketplus_order",
    "nodriver_ticketplus_wait_for_vue_ready",
    "nodriver_ticketplus_check_next_button",
    "nodriver_ticketplus_order_exclusive_code",
    "nodriver_ticketplus_read_queue_state",
    "nodriver_ticketplus_read_next_step_state",
    "nodriver_ticketplus_main",
]

# How long to watch for the URL to move after pressing "next" before handing control back
# to the main loop. Short on purpose: the main loop re-enters every cycle, so this is a
# navigation watch, not a submission timeout. Time spent here is time the stop/pause flags
# and config hot-reload are not being serviced by the main loop.
CONST_TICKETPLUS_SUBMIT_WAIT_SEC = 4.0

# Ceiling on the in-page "wait for the next button to become clickable" helper. Deliberately
# short: waiting inside the browser blocks the Python coroutine for the whole duration, and
# the main loop re-enters constantly anyway, so a long in-page wait buys nothing and only
# delays the next stop/pause check.
CONST_TICKETPLUS_BUTTON_WAIT_MS = 1500

# Hard ceiling applied on the Python side to that same call, so a wedged page cannot hold
# the coroutine past the in-page budget.
CONST_TICKETPLUS_BUTTON_WAIT_TIMEOUT_SEC = 3.0

# Minimum gap between two "press next again" attempts, so the escape hatch cannot turn
# into a click flood.
CONST_TICKETPLUS_REPRESS_COOLDOWN_SEC = 3.0

# Do not press submit again this soon after a previous press while the URL has not moved:
# the first request may still be in flight. (Reload guard, layer A.)
CONST_TICKETPLUS_SUBMIT_GUARD_SEC = 3.0

_state = {}


def _get_status():
    """Return current ticketplus status for main loop (Approach B)."""
    return {
        "purchase_completed": _state.get("purchase_completed", False),
        "is_ticket_assigned": _state.get("is_ticket_assigned", False),
    }


def _ticketplus_current_url(tab):
    """Cheap current-URL read.

    tab.target.url is a CDP-cached value, so it costs no round-trip and keeps working
    when JS execution on the page is suspended.
    """
    try:
        target = getattr(tab, 'target', None)
        if target is not None and getattr(target, 'url', None):
            return target.url
    except Exception:
        pass
    try:
        return tab.url or ""
    except Exception:
        return ""


async def _ticketplus_wait_for_navigation(tab, url_before, max_wait_sec, config_dict, debug):
    """Wait for the URL to change, up to max_wait_sec. Returns True if it moved.

    Replaces a flat `sleep(random.uniform(5, 10))` after submitting: a submit that lands
    immediately used to burn the whole sleep anyway. Polls the cached URL only, and keeps
    honouring the pause flag while it waits.
    """
    deadline = time.time() + max_wait_sec
    while time.time() < deadline:
        # Honour BOTH flags. Checking only pause meant the stop button did nothing while
        # this loop was running, which is exactly the responsiveness hole this whole
        # rewrite set out to close.
        if await check_and_handle_pause(config_dict):
            return False
        if await check_and_handle_quit(config_dict):
            debug.log("[SUBMIT] Stop requested while waiting for navigation")
            return False
        current = _ticketplus_current_url(tab)
        if current and current != url_before:
            debug.log(f"[SUBMIT] Navigated: {current}")
            return True
        await asyncio.sleep(0.15)
    return False


def _ticketplus_path_segment_count(url):
    """Path segment count with the trailing slash normalized away.

    The site 302-redirects activity URLs to a trailing-slash form (#308),
    which would inflate split('/') by one and break page-type routing.
    """
    return len(url.rstrip('/').split('/'))


async def nodriver_ticketplus_detect_layout_style(tab, config_dict=None):
    """Detect TicketPlus page layout style.

    Returns:
        dict: {
            'style': int,      # 0: unknown, 1: style_1 (expansion), 2: style_2 (simple), 3: style_3 (new Vue.js)
            'found': bool,     # whether next button found
            'button_enabled': bool  # whether button is enabled
        }
    """
    try:
        result = await evaluate_with_pause_check(tab, '''
            (function() {
                console.log("=== Layout Detection Started ===");

                // Check for row layout ticket structure (Page3 feature)
                const rowTickets = document.querySelectorAll('.row.py-1.py-md-4.rwd-margin.no-gutters.text-title');
                const expansionPanels = document.querySelectorAll('.v-expansion-panels .v-expansion-panel');

                console.log("Row ticket element count:", rowTickets.length);
                console.log("Expansion Panel element count:", expansionPanels.length);

                // If row tickets exist and no expansion panels, prioritize style 3 (Page3)
                if (rowTickets.length > 0 && expansionPanels.length === 0) {
                    const style3Button = document.querySelector("div.order-footer > div.container > div.row > div.col-sm-3.col-4 > button.nextBtn") ||
                                       document.querySelector("button.nextBtn");
                    if (style3Button) {
                        console.log("Confirmed as Page3 (Style 3) - Row layout");
                        return {
                            style: 3,
                            found: true,
                            button_enabled: style3Button.disabled === false,
                            button_class: style3Button.className,
                            debug_info: "Page3 row layout detected"
                        };
                    }
                }

                // style_3: new Vue.js layout (general check)
                const style3Button = document.querySelector("div.order-footer > div.container > div.row > div.col-sm-3.col-4 > button.nextBtn");
                if (style3Button) {
                    console.log("Found Style 3 button");
                    return {
                        style: 3,
                        found: true,
                        button_enabled: style3Button.disabled === false,
                        button_class: style3Button.className,
                        debug_info: "Standard style 3 button"
                    };
                }

                // style_2: new layout (simple)
                const style2Button = document.querySelector("div.order-footer > div.container > div.row > div > button.nextBtn");
                if (style2Button) {
                    console.log("Found Style 2 button");
                    return {
                        style: 2,
                        found: true,
                        button_enabled: style2Button.disabled === false,
                        button_class: style2Button.className,
                        debug_info: "Standard style 2 button"
                    };
                }

                // style_1: old layout (expansion) - only when expansion panels exist
                if (expansionPanels.length > 0) {
                    const style1Button = document.querySelector("div.order-footer > div.container > div.row > div > div.row > div > button.nextBtn");
                    if (style1Button) {
                        console.log("Found Style 1 button (expansion panel type)");
                        return {
                            style: 1,
                            found: true,
                            button_enabled: style1Button.disabled === false,
                            button_class: style1Button.className,
                            debug_info: "Expansion panel layout"
                        };
                    }
                }

                // Generic button search (fallback)
                const anyButton = document.querySelector("button.nextBtn");
                if (anyButton) {
                    console.log("Found generic nextBtn button, determining style based on content structure");
                    if (rowTickets.length > 0) {
                        return {
                            style: 3,
                            found: true,
                            button_enabled: anyButton.disabled === false,
                            button_class: anyButton.className,
                            debug_info: "Generic button + row structure = style 3"
                        };
                    }
                    if (expansionPanels.length > 0) {
                        return {
                            style: 1,
                            found: true,
                            button_enabled: anyButton.disabled === false,
                            button_class: anyButton.className,
                            debug_info: "Generic button + expansion panels = style 1"
                        };
                    }
                }

                console.log("Unable to detect layout style");
                return {
                    style: 0,
                    found: false,
                    button_enabled: false,
                    button_class: "",
                    debug_info: "No layout detected"
                };
            })();
        ''')

        if result is None:
            return {'style': 0, 'found': False, 'button_enabled': False, 'paused': True}

        result = util.parse_nodriver_result(result)

        return result if isinstance(result, dict) else {
            'style': 0, 'found': False, 'button_enabled': False
        }

    except Exception as exc:
        return {'style': 0, 'found': False, 'button_enabled': False, 'error': str(exc)}


async def nodriver_ticketplus_account_sign_in(tab, config_dict):
    debug = util.create_debug_logger(config_dict)
    debug.log("[TICKETPLUS SIGNIN] nodriver_ticketplus_account_sign_in")
    is_filled_form = False
    is_submited = False

    ticketplus_account = config_dict["accounts"]["ticketplus_account"]
    ticketplus_password = config_dict["accounts"]["ticketplus_password"].strip()

    # manually keyin verify code.
    country_code = ""
    try:
        my_css_selector = 'input[placeholder="\u5340\u78bc"]'
        el_country = await tab.query_selector(my_css_selector)
        if el_country:
            country_code = await el_country.apply('function (element) { return element.value; } ')
            debug.log(f"[TICKETPLUS SIGNIN] country_code: {country_code}")
    except Exception as exc:
        debug.log(f"[TICKETPLUS SIGNIN] country code error: {exc}")

    is_account_assigned = False
    try:
        my_css_selector = 'input[placeholder="\u624b\u6a5f\u865f\u78bc *"]'
        el_account = await tab.query_selector(my_css_selector)
        if el_account:
            await el_account.click()
            await el_account.apply('function (element) {element.value = ""; } ')
            await el_account.send_keys(ticketplus_account);
            is_account_assigned = True
    except Exception as exc:
        debug.log(f"[TICKETPLUS SIGNIN] account input error: {exc}")

    if is_account_assigned:
        try:
            my_css_selector = 'input[type="password"]'
            el_password = await tab.query_selector(my_css_selector)
            if el_password:
                debug.log("[TICKETPLUS SIGNIN] Entering password...")
                await el_password.click()
                await el_password.apply('function (element) {element.value = ""; } ')
                await el_password.send_keys(ticketplus_password);
                await asyncio.sleep(util.scale_humanized_delay(0.1, 0.3, config_dict))
                is_filled_form = True

                if country_code=="+886":
                    # only this case to auto sumbmit.
                    debug.log("[TICKETPLUS SIGNIN] press enter")
                    await tab.send(cdp.input_.dispatch_key_event("keyDown", code="Enter", key="Enter", text="\r", windows_virtual_key_code=13))
                    await tab.send(cdp.input_.dispatch_key_event("keyUp", code="Enter", key="Enter", text="\r", windows_virtual_key_code=13))
                    await asyncio.sleep(util.scale_humanized_delay(0.8, 1.2, config_dict))
                    # PS: ticketplus country field may not located at your target country.
                    is_submited = True
        except Exception as exc:
            debug.log(f"[TICKETPLUS SIGNIN] password input error: {exc}")
            pass

    return is_filled_form, is_submited


async def nodriver_ticketplus_is_signin(tab):
    is_user_signin = False
    try:
        cookies  = await tab.browser.cookies.get_all()
        for cookie in cookies:
            if cookie.name=='user':
                if '%22account%22:%22' in cookie.value:
                    is_user_signin = True
        cookies = None
    except Exception as exc:
        pass

    return is_user_signin


async def _ticketplus_login_form_needs_fill(tab):
    """True when the login form still needs filling.

    Replaces the old sticky _state["signin_form_filled"] flag, which was set once and
    never cleared, so a token expiry (the site logs out and re-opens the login dialog)
    permanently stopped the bot from logging back in.

    Returns False only when a visible account field already holds a value, i.e. a fill is
    in flight. Any failure returns True: re-filling is cheap and idempotent, whereas
    wrongly skipping it strands the bot at the login dialog.
    """
    try:
        result = await asyncio.wait_for(tab.evaluate('''
            (function() {
                var inputs = document.querySelectorAll(
                    'div.v-dialog input, form input, input[type="email"], input[type="tel"], input[name*="account"]');
                var visible = 0, filled = 0;
                for (var i = 0; i < inputs.length; i++) {
                    var el = inputs[i];
                    if (el.type === 'hidden' || !el.offsetParent) continue;
                    if (el.type === 'checkbox' || el.type === 'radio') continue;
                    visible++;
                    if (el.value && String(el.value).trim().length > 0) filled++;
                }
                return JSON.stringify({ visible: visible, filled: filled });
            })();
        '''), timeout=3.0)
    except Exception:
        return True

    parsed = util.parse_nodriver_result(result)
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except Exception:
            return True
    if not isinstance(parsed, dict):
        return True

    visible = parsed.get('visible', 0) or 0
    filled = parsed.get('filled', 0) or 0
    # A visible, already-populated field means a submit is in flight - leave it alone.
    return not (visible > 0 and filled > 0)


async def nodriver_ticketplus_account_auto_fill(tab, config_dict):
    # auto fill account info.
    debug = util.create_debug_logger(config_dict)
    is_user_signin = False
    if len(config_dict["accounts"]["ticketplus_account"]) > 0:
        is_user_signin = await nodriver_ticketplus_is_signin(tab)
        if not is_user_signin:
            await asyncio.sleep(0.1)
            # Guard on what the page actually shows, not on a sticky "we filled it once"
            # flag. TicketPlus force-logs-out and re-opens the login dialog when the token
            # expires (errCode 101/102/103), which is routine during a long wait; the old
            # module-level flag was never cleared, so after one expiry the bot sat in front
            # of the login dialog and never filled it again.
            is_form_pending = await _ticketplus_login_form_needs_fill(tab)
            if is_form_pending:
                is_sign_in_btn_pressed = False
                try:
                    # full screen mode.
                    my_css_selector = 'button.v-btn > span.v-btn__content > i.mdi-account'
                    sign_in_btn = await tab.query_selector(my_css_selector)
                    if sign_in_btn:
                        await sign_in_btn.click()
                        is_sign_in_btn_pressed = True
                        await asyncio.sleep(0.2)
                except Exception as exc:
                    debug.log(f"[TICKETPLUS AUTOFILL] sign-in button click error: {exc}")
                    pass

                if not is_sign_in_btn_pressed:
                    action_btns = None
                    try:
                        my_css_selector = 'div.px-4.py-3.drawerItem.cursor-pointer'
                        action_btns = await tab.query_selector_all(my_css_selector)
                    except Exception as exc:
                        debug.log(f"[TICKETPLUS AUTOFILL] drawer items query error: {exc}")
                        pass
                    if action_btns:
                        debug.log(f"[TICKETPLUS AUTOFILL] action buttons len: {len(action_btns)}")
                        if len(action_btns) >= 4:
                            try:
                                await action_btns[3].click()
                            except Exception as exc:
                                debug.log(f"[TICKETPLUS AUTOFILL] action button click error: {exc}")
                                pass

                is_filled_form, is_submited = await nodriver_ticketplus_account_sign_in(tab, config_dict)
                if is_filled_form:
                    _state["signin_form_filled"] = True

    return is_user_signin


async def _ticketplus_click_refresh_button(tab, debug):
    """Click float-btn refresh button for partial DOM update; return True if clicked."""
    try:
        btn = await tab.query_selector('button.float-btn')
        if btn:
            await btn.click()
            await asyncio.sleep(0.3)
            debug.log("[REFRESH] Clicked update button (partial refresh)")
            return True
    except Exception:
        pass
    return False


async def nodriver_ticketplus_read_queue_state(tab):
    """Read TicketPlus queue state.

    The site maintains its own truth for this: `window.isEnquene` is set/cleared by the
    enqueue handler, and the order component exposes `isPending`. Both are far more
    reliable than scraping rendered text, which changes with every site revamp.

    A full page reload while queued destroys the queue position, so this deliberately
    fails SAFE: any error, or an unreadable page, reports in_queue=True so the caller
    holds off rather than reloading on a guess.

    Returns dict:
        in_queue (bool), source (str), wait_second (int|None), degraded (bool)
    """
    try:
        result = await asyncio.wait_for(tab.evaluate('''
            (function() {
                var out = { winFlag: null, isPending: null, hasFloatBtn: false,
                            scrimUp: false, queueText: false, waitSecond: null };
                try { out.winFlag = (typeof window.isEnquene === 'undefined') ? null : !!window.isEnquene; } catch (e) {}
                try {
                    var root = document.querySelector('#app');
                    var vm = root && root.__vue__;
                    var found = null, stack = vm ? [vm] : [], guard = 0;
                    while (stack.length && !found && guard++ < 400) {
                        var cur = stack.shift();
                        if (cur && typeof cur === 'object' && 'isPending' in cur) { found = cur; break; }
                        if (cur && cur.$children) stack = stack.concat(cur.$children);
                    }
                    if (found) {
                        out.isPending = !!found.isPending;
                        if (typeof found.defaultWaitSec === 'number') out.waitSecond = found.defaultWaitSec;
                    }
                } catch (e) {}
                try { out.hasFloatBtn = !!document.querySelector('button.float-btn'); } catch (e) {}
                try {
                    var scrim = document.querySelector('.v-overlay__scrim');
                    out.scrimUp = !!(scrim && scrim.style && scrim.style.opacity === '1');
                } catch (e) {}
                try {
                    var body = document.body ? (document.body.textContent || '') : '';
                    out.queueText = body.indexOf('排隊購票') >= 0 ||
                                    body.indexOf('排隊中') >= 0 ||
                                    body.indexOf('請勿離開') >= 0 ||
                                    body.indexOf('請勿關閉網頁') >= 0;
                } catch (e) {}
                return JSON.stringify(out);
            })();
        '''), timeout=5.0)
    except Exception:
        # Unknown state -> assume queued so the caller does not reload and lose the slot.
        return {"in_queue": True, "source": "degraded", "wait_second": None, "degraded": True}

    parsed = util.parse_nodriver_result(result)
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except Exception:
            parsed = None
    if not isinstance(parsed, dict):
        return {"in_queue": True, "source": "degraded", "wait_second": None, "degraded": True}

    # Priority: the site's own flags first, page symptoms only as fallback.
    if parsed.get('winFlag') is True:
        return {"in_queue": True, "source": "window.isEnquene", "wait_second": parsed.get('waitSecond'), "degraded": False}
    if parsed.get('isPending') is True:
        return {"in_queue": True, "source": "vue.isPending", "wait_second": parsed.get('waitSecond'), "degraded": False}
    if parsed.get('winFlag') is False or parsed.get('isPending') is False:
        return {"in_queue": False, "source": "site-flag", "wait_second": None, "degraded": False}
    if parsed.get('queueText') or parsed.get('scrimUp'):
        return {"in_queue": True, "source": "dom-symptom", "wait_second": None, "degraded": False}
    return {"in_queue": False, "source": "dom-symptom", "wait_second": None, "degraded": False}


async def nodriver_ticketplus_read_next_step_state(tab):
    """Read the real enable condition behind the TicketPlus "next" button.

    The button renders as `:class="{disabledBtn: !canNextStep}"`, and on the order page
    canNextStep is:

        (serial rule) && guarantee && tickets.find(t => t.count > 0)

    where `guarantee` is the agreement checkbox (initial value false) and the serial rule
    requires a non-empty serialNumber when the session is serial-gated. Inferring "done"
    from the rendered ticket count alone misses `guarantee` entirely, which is the classic
    "button stays grey forever and nothing re-presses it" deadlock.

    Reads the component through Vue's `$el.__vue__` (present in Vue 2 production builds),
    and falls back to DOM inspection when that is unavailable.

    Returns dict with: source, can_next (bool|None), guarantee, has_ticket, serial_ok,
    total_ticket, button_enabled, disability_ok, degraded.
    """
    out = {"source": "none", "can_next": None, "guarantee": None, "has_ticket": None,
           "serial_ok": None, "total_ticket": None, "button_enabled": None,
           "disability_ok": None, "degraded": True}
    try:
        result = await asyncio.wait_for(tab.evaluate('''
            (function() {
                var res = { vue: null, buttonFound: false, buttonEnabled: false, domCount: 0 };
                try {
                    var btn = document.querySelector('button.nextBtn') || document.querySelector('.nextBtn');
                    if (btn) {
                        res.buttonFound = true;
                        res.buttonEnabled = !btn.disabled &&
                            !btn.classList.contains('v-btn--disabled') &&
                            !btn.classList.contains('disabledBtn');
                    }
                } catch (e) {}
                try {
                    var boxes = document.querySelectorAll('.count-button');
                    for (var i = 0; i < boxes.length; i++) {
                        var nodes = boxes[i].querySelectorAll('div, span, input');
                        for (var j = 0; j < nodes.length; j++) {
                            var t = (nodes[j].value !== undefined && nodes[j].value !== '')
                                ? String(nodes[j].value).trim()
                                : (nodes[j].textContent || '').trim();
                            if (/^\\d+$/.test(t)) { res.domCount += parseInt(t, 10); break; }
                        }
                    }
                } catch (e) {}
                try {
                    var root = document.querySelector('#app');
                    var vm = root && root.__vue__;
                    var found = null, stack = vm ? [vm] : [], guard = 0;
                    while (stack.length && !found && guard++ < 400) {
                        var cur = stack.shift();
                        if (cur && typeof cur === 'object' && 'canNextStep' in cur) { found = cur; break; }
                        if (cur && cur.$children) stack = stack.concat(cur.$children);
                    }
                    if (found) {
                        var hasTicket = null;
                        try {
                            hasTicket = Array.isArray(found.tickets)
                                ? !!found.tickets.find(function (t) { return t && t.count > 0; })
                                : null;
                        } catch (e) {}
                        res.vue = {
                            canNextStep: !!found.canNextStep,
                            guarantee: ('guarantee' in found) ? !!found.guarantee : null,
                            hasTicket: hasTicket,
                            totalTicket: ('totalTicket' in found) ? found.totalTicket : null,
                            serialNumber: ('serialNumber' in found) ? (String(found.serialNumber || '').length > 0) : null,
                            hasSerial: ('hasSerial' in found) ? !!found.hasSerial : null,
                            transactionValidType: (found.session && found.session.transactionValidType) || null,
                            disabilityEnable: ('disabilityEnable' in found) ? !!found.disabilityEnable : null,
                            isDisabilityValid: ('isDisabilityValid' in found) ? !!found.isDisabilityValid : null
                        };
                    }
                } catch (e) {}
                return JSON.stringify(res);
            })();
        '''), timeout=5.0)
    except Exception:
        return out

    parsed = util.parse_nodriver_result(result)
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except Exception:
            return out
    if not isinstance(parsed, dict):
        return out

    out["button_enabled"] = parsed.get('buttonFound') and parsed.get('buttonEnabled')
    vue = parsed.get('vue')
    if isinstance(vue, dict):
        disability_enable = vue.get('disabilityEnable')
        out.update({
            "source": "vue",
            "can_next": vue.get('canNextStep'),
            "guarantee": vue.get('guarantee'),
            "has_ticket": vue.get('hasTicket'),
            "serial_ok": True if vue.get('transactionValidType') != 'serial'
                         else (not vue.get('hasSerial')) or bool(vue.get('serialNumber')),
            "total_ticket": vue.get('totalTicket'),
            "disability_ok": True if not disability_enable else vue.get('isDisabilityValid'),
            "degraded": False,
        })
        return out

    # Fallback: the rendered button state is the closest available proxy for canNextStep.
    out.update({
        "source": "dom",
        "can_next": bool(parsed.get('buttonEnabled')),
        "has_ticket": (parsed.get('domCount', 0) or 0) > 0,
        "total_ticket": parsed.get('domCount', 0),
        "degraded": False,
    })
    return out


async def nodriver_ticketplus_date_auto_select(tab, config_dict):
    """TicketPlus date auto selection."""
    debug = util.create_debug_logger(config_dict)

    auto_select_mode = config_dict["date_auto_select"]["mode"]
    date_keyword = config_dict["date_auto_select"]["date_keyword"].strip()
    date_auto_fallback = config_dict.get('date_auto_fallback', False)
    pass_date_is_sold_out_enable = config_dict["tixcraft"]["pass_date_is_sold_out"]
    auto_reload_coming_soon_page_enable = config_dict["tixcraft"]["auto_reload_coming_soon_page"]

    debug.log("date_auto_select_mode:", auto_select_mode)
    debug.log("date_keyword:", date_keyword)

    area_list = None
    try:
        # TicketPlus 2026-05 revamp: a Vue sub-component wrapper div now sits between
        # #buyTicket and .sesstion-item, so a direct-child combinator matches nothing.
        # Use a descendant combinator (still matches the old direct-child layout too).
        area_list = await tab.query_selector_all('div#buyTicket div.sesstion-item')
        if area_list and len(area_list) == 0:
            debug.log("empty date item, need retry.")
            await tab.sleep(0.2)
    except Exception as exc:
        debug.log("find #buyTicket fail:", exc)

    find_ticket_text_list = ['>\u7acb\u5373\u8cfc', '\u5c1a\u672a\u958b\u8ce3']
    sold_out_text_list = ['\u92b7\u552e\u4e00\u7a7a']

    matched_blocks = None
    formated_area_list = None
    is_vue_ready = True

    if area_list and len(area_list) > 0:
        debug.log("date_list_count:", len(area_list))

        formated_area_list = []
        for row in area_list:
            row_text = ""
            row_html = ""
            try:
                row_html = await row.get_html()
                row_text = util.remove_html_tags(row_html)
            except Exception as exc:
                debug.log("Date item processing failed:", exc)
                break

            if len(row_text) > 0:
                if util.reset_row_text_if_match_keyword_exclude(config_dict, row_text):
                    row_text = ""

            if len(row_text) > 0:
                if '<div class="v-progress-circular__info"></div>' in row_html:
                    is_vue_ready = False
                    break

            if len(row_text) > 0:
                row_is_enabled = False
                for text_item in find_ticket_text_list:
                    if text_item in row_html:
                        row_is_enabled = True
                        break

                if row_is_enabled and pass_date_is_sold_out_enable:
                    for sold_out_item in sold_out_text_list:
                        if sold_out_item in row_text:
                            row_is_enabled = False
                            debug.log(f"match sold out text: {sold_out_item}, skip this row.")
                            break

                if row_is_enabled:
                    formated_area_list.append(row)

        debug.log("formated_area_list count:", len(formated_area_list))

        if len(date_keyword) == 0:
            matched_blocks = formated_area_list
        else:
            matched_blocks = []
            try:
                original_keyword = config_dict["date_auto_select"]["date_keyword"].strip()
                keyword_array = json.loads("[" + original_keyword + "]")

                debug.log(f"[TicketPlus DATE] Applying keyword filter: {keyword_array}")

                for i, row in enumerate(formated_area_list):
                    row_text = ""
                    try:
                        row_html = await row.get_html()
                        row_text = util.remove_html_tags(row_html).lower()
                    except Exception as exc:
                        debug.log(f"[TicketPlus DATE] Failed to get row text: {exc}")
                        continue

                    for keyword_item in keyword_array:
                        sub_keywords = [kw.strip() for kw in keyword_item.split(' ') if kw.strip()]
                        is_match = all(sub_kw.lower() in row_text for sub_kw in sub_keywords)

                        if is_match:
                            matched_blocks.append(row)
                            debug.log(f"[TicketPlus DATE] Keyword '{keyword_item}' matched row {i}")
                            break

            except json.JSONDecodeError as exc:
                debug.log(f"[TicketPlus DATE] Keyword parse error: {exc}")
                debug.log(f"[TicketPlus DATE] Treating as 'all keywords failed'")
                matched_blocks = []
            except Exception as exc:
                debug.log(f"[TicketPlus DATE] Keyword matching failed: {exc}")
                matched_blocks = []

        if len(matched_blocks) == 0 and date_keyword and len(date_keyword) > 0:
            if date_auto_fallback:
                debug.log(f"[TicketPlus DATE FALLBACK] date_auto_fallback=true, triggering auto fallback")
                matched_blocks = formated_area_list
            else:
                debug.log(f"[TicketPlus DATE FALLBACK] date_auto_fallback=false, fallback is disabled")
                debug.log(f"[TicketPlus DATE SELECT] No date selected, will check if reload needed")
    else:
        debug.log("date date-time-position is None or empty")

    is_date_clicked = False
    if is_vue_ready and formated_area_list and len(formated_area_list) > 0:
        try:
            original_keyword = config_dict["date_auto_select"]["date_keyword"].strip()

            # Primary: read sessionId from Vue data layer, navigate directly
            # Avoids clicking loading-state placeholder containers
            vue_data = await tab.evaluate('''
                (function() {
                    const el = document.querySelector('.eventClass');
                    if (!el || !el.__vue__) return { ready: false };
                    const sessions = el.__vue__.$data.sessions || [];
                    const loaded = sessions.filter(function(s) { return s.loadingStatusFinished; });
                    return {
                        ready: loaded.length > 0,
                        sessions: loaded.map(function(s) {
                            return { sessionId: s.sessionId, date: s.date || '', name: s.name || '' };
                        })
                    };
                })();
            ''')

            if isinstance(vue_data, dict) and vue_data.get('ready') and vue_data.get('sessions'):
                sessions = vue_data['sessions']
                target_session = None
                try:
                    kw_array = json.loads("[" + original_keyword + "]")
                except Exception:
                    kw_array = [original_keyword.strip('"').strip("'").strip()]

                for s in sessions:
                    session_text = (s.get('date', '') + ' ' + s.get('name', '')).lower()
                    for kw_item in kw_array:
                        sub_kws = [k.strip() for k in kw_item.split(' ') if k.strip()]
                        if all(k.lower() in session_text for k in sub_kws):
                            target_session = s
                            break
                    if target_session:
                        break

                if not target_session and date_auto_fallback and sessions:
                    debug.log("[TicketPlus DATE FALLBACK] Vue data fallback: using first loaded session")
                    target_session = sessions[0]

                if target_session:
                    session_id = target_session['sessionId']
                    # Known honeypot sessionId: TicketPlus API returns fake data to detected bots
                    KNOWN_FAKE_SESSION_IDS = ['c18900a1d5f295218fe60b982d7ece96']
                    if session_id in KNOWN_FAKE_SESSION_IDS:
                        debug.log(f"[TicketPlus DATE] WARNING: API returned known fake session data (anti-bot honeypot detected). sessionId={session_id}")
                        debug.log("[TicketPlus DATE] Bot may be flagged by TicketPlus. Skipping navigation to avoid invalid order page.")
                    else:
                        current_url = tab.url if hasattr(tab, 'url') else ''
                        if not current_url:
                            current_url = await tab.evaluate('window.location.href')
                        event_id = current_url.split('/activity/')[-1].split('/')[0].split('?')[0]
                        order_url = 'https://ticketplus.com.tw/order/' + event_id + '/' + session_id
                        debug.log(f"[TicketPlus DATE] Vue data: date={target_session.get('date', '')} sessionId={session_id}")
                        await tab.get(order_url)
                        is_date_clicked = True

        except Exception as exc:
            debug.log(f"[TicketPlus DATE] Vue data navigation failed: {exc}")

    if not is_date_clicked and is_vue_ready and formated_area_list and len(formated_area_list) > 0:
        try:
            original_keyword = config_dict["date_auto_select"]["date_keyword"].strip()
            click_result = await tab.evaluate(f'''
                (function() {{
                    const originalKeyword = '{original_keyword}';
                    const autoSelectMode = '{auto_select_mode}';
                    const dateAutoFallback = {'true' if date_auto_fallback else 'false'};

                    console.log('[TicketPlus] Starting date selection - keyword:', originalKeyword, 'mode:', autoSelectMode, 'fallback:', dateAutoFallback);

                    let sessionContainers = Array.from(document.querySelectorAll('div#buyTicket div.sesstion-item'))
                        .filter(c => c.querySelector('button.nextBtn'));

                    if (sessionContainers.length === 0) {{
                        sessionContainers = Array.from(document.querySelectorAll('div#buyTicket div.row.pa-4'))
                            .filter(c => c.querySelector('button.nextBtn'));
                    }}

                    console.log('[TicketPlus] Found session containers:', sessionContainers.length);

                    let matchedContainers = [];

                    if (originalKeyword && originalKeyword.trim() !== '') {{
                        let keywords = [];
                        if (originalKeyword.includes(',')) {{
                            keywords = originalKeyword.split(',')
                                .map(k => k.trim().replace(/^["']|["']$/g, ''))
                                .filter(k => k.length > 0);
                        }} else {{
                            keywords = [originalKeyword.replace(/^["']|["']$/g, '').trim()];
                        }}

                        console.log('[TicketPlus] Parsed keywords:', keywords);

                        for (let i = 0; i < sessionContainers.length; i++) {{
                            const container = sessionContainers[i];
                            const text = container.textContent || '';
                            const normalizedText = text.replace(/[\\s\\u3000]/g, '').toLowerCase();

                            for (let keyword of keywords) {{
                                const normalizedKeyword = keyword.replace(/[\\s\\u3000]/g, '').toLowerCase();
                                if (normalizedText.includes(normalizedKeyword)) {{
                                    matchedContainers.push(container);
                                    console.log('[TicketPlus] Keyword "' + keyword + '" matched container ' + i);
                                    console.log('  -> Text preview:', text.substring(0, 100).replace(/\\n/g, ' '));
                                    break;
                                }}
                            }}
                        }}
                    }} else {{
                        matchedContainers = sessionContainers;
                        console.log('[TicketPlus] No keyword specified, using all', sessionContainers.length, 'containers');
                    }}

                    if (matchedContainers.length === 0 && originalKeyword && originalKeyword.trim() !== '') {{
                        if (dateAutoFallback) {{
                            console.log('[TicketPlus DATE FALLBACK] date_auto_fallback=true, triggering auto fallback');
                            matchedContainers = sessionContainers;
                        }} else {{
                            console.log('[TicketPlus DATE FALLBACK] date_auto_fallback=false, fallback is disabled');
                            console.log('[TicketPlus DATE SELECT] No date selected, will reload page and retry');
                            return {{
                                success: false,
                                error: 'No keyword matches and fallback is disabled',
                                strict_mode: true
                            }};
                        }}
                    }}

                    if (matchedContainers.length === 0) {{
                        console.log('[TicketPlus ERROR] No session containers found');
                        return {{
                            success: false,
                            error: 'No session containers found',
                            debug: {{
                                keyword: originalKeyword,
                                mode: autoSelectMode,
                                totalContainers: sessionContainers.length
                            }}
                        }};
                    }}

                    let targetIndex = 0;
                    if (autoSelectMode === 'from bottom to top') {{
                        targetIndex = matchedContainers.length - 1;
                    }} else if (autoSelectMode === 'center') {{
                        targetIndex = Math.floor(matchedContainers.length / 2);
                    }} else if (autoSelectMode === 'random') {{
                        targetIndex = Math.floor(Math.random() * matchedContainers.length);
                    }}

                    let targetContainer = matchedContainers[targetIndex];
                    const containerText = (targetContainer.textContent || '').substring(0, 150).replace(/\\n/g, ' ');
                    console.log('[TicketPlus TARGET] Selected container [' + targetIndex + '/' + matchedContainers.length + ']');
                    console.log('  -> Preview:', containerText);

                    let buyButton = targetContainer.querySelector('button.nextBtn');
                    if (!buyButton) {{
                        buyButton = targetContainer.querySelector('button');
                    }}

                    if (!buyButton) {{
                        console.log('[TicketPlus ERROR] No buy button found in container');
                        return {{
                            success: false,
                            error: 'No buy button found in container',
                            targetText: containerText
                        }};
                    }}

                    const buttonText = buyButton.textContent || '';
                    console.log('[TicketPlus BUTTON] Found button:', buttonText);

                    try {{
                        const event = new MouseEvent('click', {{
                            bubbles: true,
                            cancelable: true,
                            view: window
                        }});
                        buyButton.dispatchEvent(event);
                        console.log('[TicketPlus SUCCESS] Button clicked successfully');
                        return {{
                            success: true,
                            action: 'button_clicked',
                            matchedCount: matchedContainers.length,
                            targetText: containerText,
                            buttonText: buttonText
                        }};
                    }} catch (e) {{
                        console.log('[TicketPlus ERROR] Click failed:', e.message);
                        return {{
                            success: false,
                            error: 'Click failed: ' + e.message,
                            targetText: containerText
                        }};
                    }}
                }})();
            ''')

            parsed_result = util.parse_nodriver_result(click_result)

            if isinstance(parsed_result, dict) and parsed_result.get('success'):
                debug.log(f"Date selection and click successful: {parsed_result.get('action', 'unknown')}")
                debug.log(f"   Target text: {parsed_result.get('targetText', '')}")
                is_date_clicked = True
            else:
                debug.log(f"Date selection and click failed: {parsed_result.get('error', 'unknown') if isinstance(parsed_result, dict) else str(parsed_result)}")

        except Exception as exc:
            debug.log("JavaScript date selection click failed:", exc)

    if not is_date_clicked:
        if debug.enabled:
            if not is_vue_ready:
                debug.log("[TicketPlus DATE] Vue.js not ready, waiting for page to load...")
            elif not formated_area_list or len(formated_area_list) == 0:
                debug.log("[TicketPlus DATE] No available tickets (all sold out), waiting for refresh...")

        if auto_reload_coming_soon_page_enable and is_vue_ready and (not formated_area_list or len(formated_area_list) == 0):
            try:
                reload_interval = config_dict["advanced"].get("auto_reload_page_interval", 0)
                if reload_interval > 0:
                    debug.log(f"[TicketPlus DATE] Waiting {reload_interval}s before auto-reload...")
                    await asyncio.sleep(reload_interval)
                else:
                    await asyncio.sleep(1.0)

                clicked = await _ticketplus_click_refresh_button(tab, debug)
                if not clicked:
                    await tab.reload()
                    debug.log("[TicketPlus DATE] Page reloaded, waiting for content...")
                    await asyncio.sleep(0.5)
            except Exception as exc:
                debug.log(f"[TicketPlus DATE] Auto reload failed: {exc}")

    return is_date_clicked


async def nodriver_ticketplus_unified_select(tab, config_dict, area_keyword):
    """TicketPlus unified selector - language-independent ticket type/area selection."""
    debug = util.create_debug_logger(config_dict)
    auto_select_mode = config_dict["area_auto_select"]["mode"]
    area_auto_fallback = config_dict.get('area_auto_fallback', False)
    ticket_number = config_dict["ticket_number"]
    keyword_exclude = config_dict.get("keyword_exclude", "")

    debug.log(f"Unified selector started - keyword: {area_keyword}, tickets: {ticket_number}")

    is_selected = False

    try:
        if await check_and_handle_pause(config_dict):
            return False

        exclude_keywords = []
        if keyword_exclude:
            try:
                exclude_keywords = json.loads("[" + keyword_exclude + "]")
            except:
                if util.CONST_KEYWORD_DELIMITER in keyword_exclude:
                    exclude_keywords = [kw.strip() for kw in keyword_exclude.split(util.CONST_KEYWORD_DELIMITER) if kw.strip()]
                else:
                    exclude_keywords = [keyword_exclude.strip()] if keyword_exclude.strip() else []

        # Wait for Vue.js elements to render
        auto_reload_interval = config_dict["advanced"].get("auto_reload_page_interval", 5)
        max_vue_wait = max(6.0, min(15.0, auto_reload_interval * 2))
        vue_check_interval = 0.15
        vue_wait_start = time.time()
        vue_elements_found = False
        last_log_time = 0

        while time.time() - vue_wait_start < max_vue_wait:
            if await check_and_handle_pause(config_dict):
                return False

            try:
                vue_check = await tab.evaluate('''
                    (function() {
                        const panels = document.querySelectorAll('.v-expansion-panel').length;
                        const countBtn = document.querySelectorAll('.count-button .mdi-plus').length;
                        const rowTickets = document.querySelectorAll('.row.py-1.py-md-4').length;
                        return {
                            panels: panels,
                            countBtn: countBtn,
                            rowTickets: rowTickets,
                            hasElements: panels > 0 || countBtn > 0 || rowTickets > 0
                        };
                    })();
                ''')

                if isinstance(vue_check, list):
                    vue_check = {item[0]: item[1].get('value') if isinstance(item[1], dict) else item[1] for item in vue_check}

                elapsed = time.time() - vue_wait_start
                if elapsed - last_log_time >= 1.0:
                    debug.log(f"[VUE WAIT] {elapsed:.1f}s - panels:{vue_check.get('panels', 0)}, countBtn:{vue_check.get('countBtn', 0)}, rowTickets:{vue_check.get('rowTickets', 0)}")
                    last_log_time = elapsed

                if vue_check.get('hasElements', False):
                    vue_elements_found = True
                    debug.log(f"[VUE WAIT] Vue elements found after {elapsed:.1f}s")
                    await asyncio.sleep(0.1)
                    break

            except Exception as e:
                debug.log(f"[VUE WAIT] Check error: {e}")

            await asyncio.sleep(vue_check_interval)

        if not vue_elements_found:
            debug.log(f"[VUE WAIT] Timeout after {max_vue_wait:.1f}s, Vue elements not found")
            return False

        # json.dumps produces a valid JS string/array literal and escapes quotes and
        # backslashes. Interpolating raw user text used to break the whole script when a
        # keyword contained an apostrophe, which surfaced only as "selection failed".
        # Ticket-type preference: pick the perk variant over the plain one when both exist.
        ticket_type_raw = config_dict.get("advanced", {}).get("ticket_type_keyword", "")
        ticket_type_terms = []
        if isinstance(ticket_type_raw, str) and ticket_type_raw.strip():
            for chunk in ticket_type_raw.replace(",", ";").split(";"):
                cleaned = chunk.strip().strip('"').strip()
                if cleaned:
                    ticket_type_terms.append(cleaned)
        ticket_type_terms_js = json.dumps(ticket_type_terms, ensure_ascii=True)

        area_keyword_js = json.dumps(area_keyword or "")
        auto_select_mode_js = json.dumps(auto_select_mode or "")
        exclude_keywords = json.dumps(exclude_keywords)

        js_result = await tab.evaluate(f'''
            (function() {{
                const keyword = {area_keyword_js};
                const ticketNumber = {ticket_number};
                const autoSelectMode = {auto_select_mode_js};
                const areaAutoFallback = {'true' if area_auto_fallback else 'false'};
                // Every whitespace-separated term must match (AND). Normalised here once so
                // the comparison side stays cheap.
                const keywordTerms = keyword.split(/\\s+/)
                    .map(function (s) {{ return s.replace(/,/g, '').trim(); }})
                    .filter(function (s) {{ return s.length > 0; }});
                // Preference list for choosing BETWEEN ticket rows inside the matched zone
                // (e.g. plain ticket vs the "+ perk" variant). OR semantics, first hit wins.
                const ticketTypeTerms = {ticket_type_terms_js};
                const excludeKeywords = {exclude_keywords};

                console.log('Unified selector execution - keyword:', keyword, 'tickets:', ticketNumber, 'mode:', autoSelectMode, 'fallback:', areaAutoFallback);

                // Zone rows render the price with a thousands separator ("NT.5,380") while
                // users type it without ("5380"), so a raw includes() never matches and the
                // failure is silent. Normalise both sides before comparing.
                function norm(s) {{
                    return (s || '').replace(/,/g, '').replace(/\\s+/g, ' ').trim();
                }}

                function matchesKeywords(name) {{
                    if (!keywordTerms.length) return false;
                    const n = norm(name);
                    // All terms in one priority must be present (AND). Previously only the
                    // first two terms were honoured and the rest were silently dropped.
                    return keywordTerms.every(function (kw) {{ return n.indexOf(kw) >= 0; }});
                }}

                function isSoldOut(element) {{
                    // The page tags sold-out rows with a CSS class; trust that first and
                    // fall back to text matching only when the class is absent.
                    try {{
                        if (element.querySelector && element.querySelector('.soldout')) return true;
                    }} catch (e) {{}}
                    const text = element.textContent || '';
                    const soldOutPatterns = [/\u5269\u9918\\s*0(?!\\d)/, /\u5269\u9918\\s*:\\s*0(?!\\d)/, /sold\\s*out/i, /\u552e\u5b8c/, /\u5df2\u552e\u5b8c/, /\u552e\u7f44/, /\u7121\u5eab\u5b58/];
                    const availablePatterns = [/\u71b1\u8ce3\u4e2d/, /\u71b1\u8ce3/, /\u71b1\u552e/, /\u53ef\u8cfc\u8cb7/, /available/i, /\u5269\u9918\\s*[1-9]\\d*/];

                    for (let pattern of soldOutPatterns) {{
                        if (pattern.test(text)) {{
                            for (let avail of availablePatterns) {{
                                if (avail.test(text)) return false;
                            }}
                            return true;
                        }}
                    }}
                    return false;
                }}

                function containsExcludeKeywords(name) {{
                    if (!excludeKeywords || excludeKeywords.length === 0) return false;
                    const n = norm(name);
                    for (let kw of excludeKeywords) {{
                        if (kw && n.indexOf(norm(kw)) >= 0) return true;
                    }}
                    return false;
                }}

                // Reads the stepper's current value. TicketPlus renders it as a bare number
                // inside .count-button; an <input> is used in some layouts.
                function readCount(box) {{
                    if (!box) return null;
                    const input = box.querySelector('input');
                    if (input && input.value !== undefined && input.value !== '') {{
                        const iv = parseInt(String(input.value).trim(), 10);
                        if (!isNaN(iv)) return iv;
                    }}
                    const nodes = box.querySelectorAll('div, span');
                    for (let i = 0; i < nodes.length; i++) {{
                        const t = (nodes[i].textContent || '').trim();
                        if (/^\\d+$/.test(t)) return parseInt(t, 10);
                    }}
                    return null;
                }}

                // Authoritative total from the Vue component, used only to decide whether an
                // unreadable stepper is safe to touch.
                function vueTotalTicket() {{
                    try {{
                        var root = document.querySelector('#app');
                        var vm = root && root.__vue__;
                        var stack = vm ? [vm] : [], guard = 0;
                        while (stack.length && guard++ < 400) {{
                            var cur = stack.shift();
                            if (cur && typeof cur === 'object' && typeof cur.totalTicket === 'number') {{
                                return cur.totalTicket;
                            }}
                            if (cur && cur.$children) stack = stack.concat(cur.$children);
                        }}
                    }} catch (e) {{}}
                    return null;
                }}

                // A zone panel can hold SEVERAL ticket rows - e.g. "全票" and
                // "全票+加購福利" - each with its own stepper. Taking the first
                // .count-button therefore always bought the plain ticket and silently gave up the
                // bundled perk, which on some events cannot be added afterwards.

                // Largest ancestor that still contains exactly this one stepper == the ticket row.
                // Derived from the DOM shape rather than class names, which vary between layouts.
                function rowElementOf(box, panel) {{
                    let el = box;
                    while (el.parentElement && el.parentElement !== panel) {{
                        const parent = el.parentElement;
                        if (parent.querySelectorAll('.count-button').length > 1) break;
                        el = parent;
                    }}
                    return el;
                }}

                function isRowSoldOut(text) {{
                    return /售完|售罄|sold\\s*out/i.test(text);
                }}

                // Returns the stepper to drive, preferring a row that matches ticketTypeTerms.
                function pickTicketBox(panel) {{
                    const boxes = panel.querySelectorAll('.count-button');
                    const candidates = [];
                    for (let i = 0; i < boxes.length; i++) {{
                        const box = boxes[i];
                        if (!box.querySelector('.mdi-plus')) continue;   // sold out rows have no stepper
                        const rowText = norm(rowElementOf(box, panel).textContent || '');
                        if (isRowSoldOut(rowText)) continue;
                        candidates.push({{ box: box, text: rowText }});
                    }}
                    if (!candidates.length) return null;
                    if (ticketTypeTerms.length) {{
                        for (let i = 0; i < candidates.length; i++) {{
                            const c = candidates[i];
                            const hit = ticketTypeTerms.some(function (t) {{ return c.text.indexOf(t) >= 0; }});
                            if (hit) {{
                                return {{ box: c.box, preferred: true, rowText: c.text.slice(0, 40),
                                         rows: candidates.length }};
                            }}
                        }}
                    }}
                    return {{ box: candidates[0].box, preferred: false,
                             rowText: candidates[0].text.slice(0, 40), rows: candidates.length }};
                }}

                // Clicking plus N times unconditionally is NOT idempotent: the main loop
                // re-enters this selector every cycle while the page stays on /order/, so a
                // failed submit used to leave 2N, 3N... tickets selected. Drive the stepper
                // to the target instead, and no-op when it is already there.
                function applyCount(scope, target) {{
                    const picked = pickTicketBox(scope);
                    if (!picked) return {{ ok: false, reason: 'no-plus' }};
                    const box = picked.box;
                    const plus = box.querySelector('.mdi-plus');
                    const minus = box.querySelector('.mdi-minus');
                    if (!plus) return {{ ok: false, reason: 'no-plus' }};
                    let before = readCount(box);
                    if (before === null) {{
                        // Never assume zero here. Assuming zero on an unreadable stepper
                        // re-adds `target` tickets on EVERY main-loop cycle, which is the
                        // exact over-selection this function exists to prevent. Only the
                        // component's own total can vouch that nothing is selected yet.
                        const total = vueTotalTicket();
                        if (total === 0) {{
                            before = 0;
                        }} else {{
                            return {{ ok: false, reason: 'unreadable-count', vueTotal: total }};
                        }}
                    }}
                    const current = before;
                    let delta = target - current;
                    const meta = {{ rowText: picked.rowText, preferred: picked.preferred, rows: picked.rows }};
                    if (delta === 0) {{
                        return {{ ok: true, before: before, clicks: 0, direction: 'none',
                                 rowText: meta.rowText, preferred: meta.preferred, rows: meta.rows }};
                    }}
                    let clicks = 0;
                    const budget = Math.min(Math.abs(delta), 20);
                    if (delta > 0) {{
                        for (let i = 0; i < budget; i++) {{ plus.click(); clicks++; }}
                        return {{ ok: true, before: before, clicks: clicks, direction: 'up',
                                 rowText: meta.rowText, preferred: meta.preferred, rows: meta.rows }};
                    }}
                    if (!minus) return {{ ok: false, reason: 'over-count-no-minus', before: before }};
                    for (let i = 0; i < budget; i++) {{ minus.click(); clicks++; }}
                    return {{ ok: true, before: before, clicks: clicks, direction: 'down',
                             rowText: meta.rowText, preferred: meta.preferred, rows: meta.rows }};
                }}

                function getTargetIndex(items, mode) {{
                    const count = items.length;
                    if (count === 0) return -1;
                    switch(mode) {{
                        case 'from top to bottom': return 0;
                        case 'from bottom to top': return count - 1;
                        case 'center': return Math.floor((count - 1) / 2);
                        case 'random': return Math.floor(Math.random() * count);
                        default: return 0;
                    }}
                }}

                const hasExpansionPanel = document.querySelector('.v-expansion-panel');
                const hasCountButton = document.querySelector('.count-button .mdi-plus');

                console.log('hasExpansionPanel:', !!hasExpansionPanel, 'hasCountButton:', !!hasCountButton);

                if (hasExpansionPanel) {{
                    // Select innermost zone panels only (the leaf panels containing .mdi-plus add buttons).
                    // :not(:has(.seats-area)) excludes any panel that wraps another .seats-area (price-tier
                    // group panels), leaving only the clickable zone panels in both flat and nested layouts.
                    // :has() requires Chrome 105+; zendriver enforces Chrome 145+, so this is safe.
                    const panels = document.querySelectorAll('.seats-area .v-expansion-panel:not(:has(.seats-area))');
                    const validPanels = [];
                    const soldOutNames = [];

                    for (let i = 0; i < panels.length; i++) {{
                        const panel = panels[i];
                        const nameEl = panel.querySelector('.v-expansion-panel-header');
                        if (nameEl) {{
                            const name = nameEl.textContent.trim().replace(/\\s+/g, ' ');
                            if (containsExcludeKeywords(name)) continue;
                            if (isSoldOut(panel)) {{
                                soldOutNames.push(name);
                            }} else {{
                                validPanels.push({{ panel, name, index: i }});
                            }}
                        }}
                    }}

                    console.log('Valid panels:', validPanels.length);
                    if (validPanels.length === 0) {{
                        return {{ success: false, message: 'No valid panels' }};
                    }}

                    let target = null;
                    if (keywordTerms.length) {{
                        target = validPanels.find(p => matchesKeywords(p.name));
                    }}
                    if (!target && keywordTerms.length && !areaAutoFallback) {{
                        const keywordInSoldOut = soldOutNames.some(n => matchesKeywords(n));
                        return {{ success: false, strict_mode: true, attempted_keyword: keyword, keyword_in_sold_out: keywordInSoldOut }};
                    }}
                    if (!target) {{
                        const idx = getTargetIndex(validPanels, autoSelectMode);
                        target = validPanels[idx];
                    }}

                    if (!target) {{
                        return {{ success: false, message: 'No target panel' }};
                    }}

                    const header = target.panel.querySelector('.v-expansion-panel-header');
                    const isExpanded = target.panel.classList.contains('v-expansion-panel--active');
                    if (!isExpanded && header) {{
                        console.log('Clicking to expand:', target.name);
                        header.click();
                    }}

                    // Vue renders the panel body lazily, so on a freshly expanded panel the
                    // stepper does not exist yet in this same synchronous pass -> needRetry.
                    let plusBtn = target.panel.querySelector('.mdi-plus') ||
                                  target.panel.querySelector('.count-button .mdi-plus');

                    if (plusBtn) {{
                        const applied = applyCount(target.panel, ticketNumber);
                        console.log('applyCount:', JSON.stringify(applied));
                        if (applied.ok) {{
                            return {{ success: true, type: 'expansion_panel', selected: target.name,
                                     clicked: true, countBefore: applied.before,
                                     countClicks: applied.clicks, countDirection: applied.direction,
                                     rowText: applied.rowText, rowPreferred: applied.preferred,
                                     rowCount: applied.rows }};
                        }}
                        return {{ success: true, type: 'expansion_panel', selected: target.name,
                                 clicked: false, needRetry: true, applyReason: applied.reason }};
                    }}

                    return {{ success: true, type: 'expansion_panel', selected: target.name, clicked: false, needRetry: true }};

                }} else if (hasCountButton) {{
                    const rows = document.querySelectorAll('.row.py-1.py-md-4');
                    const validRows = [];
                    const soldOutRowNames = [];

                    for (let row of rows) {{
                        const plusBtn = row.querySelector('.count-button .mdi-plus');
                        if (!plusBtn) continue;

                        const nameEl = row.querySelector('.font-weight-medium');
                        if (nameEl) {{
                            const name = nameEl.textContent.trim();
                            if (containsExcludeKeywords(name)) continue;
                            if (isSoldOut(row)) {{
                                soldOutRowNames.push(name);
                            }} else {{
                                validRows.push({{ row, name, plusBtn }});
                            }}
                        }}
                    }}

                    console.log('Valid rows:', validRows.length);
                    if (validRows.length === 0) {{
                        return {{ success: false, message: 'No valid rows' }};
                    }}

                    let target = null;
                    if (keywordTerms.length) {{
                        target = validRows.find(r => matchesKeywords(r.name));
                    }}
                    if (!target && keywordTerms.length && !areaAutoFallback) {{
                        const keywordInSoldOut = soldOutRowNames.some(n => matchesKeywords(n));
                        return {{ success: false, strict_mode: true, attempted_keyword: keyword, keyword_in_sold_out: keywordInSoldOut }};
                    }}
                    if (!target) {{
                        const idx = getTargetIndex(validRows, autoSelectMode);
                        target = validRows[idx];
                    }}

                    if (target && target.plusBtn) {{
                        const applied = applyCount(target.row, ticketNumber);
                        console.log('applyCount(row):', JSON.stringify(applied));
                        if (applied.ok) {{
                            return {{ success: true, type: 'count_button', selected: target.name,
                                     clicked: true, countBefore: applied.before,
                                     countClicks: applied.clicks, countDirection: applied.direction }};
                        }}
                        return {{ success: false, type: 'count_button', selected: target.name,
                                 clicked: false, message: 'applyCount failed: ' + applied.reason }};
                    }}
                }}

                return {{ success: false, message: 'No selectable elements found' }};
            }})();
        ''')

        result = util.parse_nodriver_result(js_result)

        if isinstance(result, dict):
            is_selected = result.get('success', False) and result.get('clicked', False)

            if result.get('needRetry', False):
                apply_reason = result.get('applyReason')
                if apply_reason == 'unreadable-count':
                    # Deliberate refusal, not a glitch: the stepper value could not be read
                    # and the component total says something is already selected, so
                    # clicking again could overshoot the per-order limit. Say so loudly -
                    # if this repeats every cycle the page markup has changed.
                    debug.log("[RETRY] Stepper value unreadable and tickets already selected; "
                              "refusing to click (would risk over-selecting). Retrying...")
                else:
                    debug.log("[RETRY] Panel expanded but plus button not found, retrying...")

                await asyncio.sleep(0.3)

                for retry in range(5):
                    retry_result = await tab.evaluate(f'''
                        (function() {{
                            const target = {ticket_number};
                            const ticketTypeTerms = {ticket_type_terms_js};

                            function normRow(s) {{
                                return (s || '').replace(/,/g, '').replace(/\\s+/g, ' ').trim();
                            }}

                            // Mirror of the main pass: a zone can contain several ticket rows
                            // (plain vs "+ perk"); pick the preferred one instead of the first.
                            function rowElementOf(box, panel) {{
                                let el = box;
                                while (el.parentElement && el.parentElement !== panel) {{
                                    const parent = el.parentElement;
                                    if (parent.querySelectorAll('.count-button').length > 1) break;
                                    el = parent;
                                }}
                                return el;
                            }}

                            function pickTicketBox(panel) {{
                                const boxes = panel.querySelectorAll('.count-button');
                                const candidates = [];
                                for (let i = 0; i < boxes.length; i++) {{
                                    const box = boxes[i];
                                    if (!box.querySelector('.mdi-plus')) continue;
                                    const rowText = normRow(rowElementOf(box, panel).textContent || '');
                                    if (/售完|售罄|sold\\s*out/i.test(rowText)) continue;
                                    candidates.push({{ box: box, text: rowText }});
                                }}
                                if (!candidates.length) return null;
                                if (ticketTypeTerms.length) {{
                                    for (let i = 0; i < candidates.length; i++) {{
                                        const c = candidates[i];
                                        if (ticketTypeTerms.some(function (t) {{ return c.text.indexOf(t) >= 0; }})) {{
                                            return {{ box: c.box, preferred: true, rowText: c.text.slice(0, 40) }};
                                        }}
                                    }}
                                }}
                                return {{ box: candidates[0].box, preferred: false,
                                         rowText: candidates[0].text.slice(0, 40) }};
                            }}

                            function readCount(box) {{
                                const input = box.querySelector('input');
                                if (input && input.value !== undefined && input.value !== '') {{
                                    const iv = parseInt(String(input.value).trim(), 10);
                                    if (!isNaN(iv)) return iv;
                                }}
                                const nodes = box.querySelectorAll('div, span');
                                for (let i = 0; i < nodes.length; i++) {{
                                    const t = (nodes[i].textContent || '').trim();
                                    if (/^\\d+$/.test(t)) return parseInt(t, 10);
                                }}
                                return null;
                            }}

                            function vueTotalTicket() {{
                                try {{
                                    var root = document.querySelector('#app');
                                    var vm = root && root.__vue__;
                                    var stack = vm ? [vm] : [], guard = 0;
                                    while (stack.length && guard++ < 400) {{
                                        var cur = stack.shift();
                                        if (cur && typeof cur === 'object' && typeof cur.totalTicket === 'number') {{
                                            return cur.totalTicket;
                                        }}
                                        if (cur && cur.$children) stack = stack.concat(cur.$children);
                                    }}
                                }} catch (e) {{}}
                                return null;
                            }}

                            // Same idempotency rule as the main pass: drive the stepper to
                            // the target rather than blind-clicking, so repeated retries
                            // cannot stack extra tickets. An unreadable stepper is NOT
                            // assumed to be zero - see the main pass for why.
                            function applyCount(scope) {{
                                const picked = pickTicketBox(scope);
                                if (!picked) return null;
                                const box = picked.box;
                                const plus = box.querySelector('.mdi-plus');
                                const minus = box.querySelector('.mdi-minus');
                                if (!plus) return null;
                                let before = readCount(box);
                                if (before === null) {{
                                    if (vueTotalTicket() === 0) {{
                                        before = 0;
                                    }} else {{
                                        return {{ clicked: false, before: null, clicks: 0, reason: 'unreadable-count' }};
                                    }}
                                }}
                                const current = before;
                                const delta = target - current;
                                if (delta === 0) return {{ clicked: true, before: before, clicks: 0 }};
                                const budget = Math.min(Math.abs(delta), 20);
                                if (delta > 0) {{
                                    for (let i = 0; i < budget; i++) plus.click();
                                    return {{ clicked: true, before: before, clicks: budget }};
                                }}
                                if (!minus) return {{ clicked: false, before: before, clicks: 0 }};
                                for (let i = 0; i < budget; i++) minus.click();
                                return {{ clicked: true, before: before, clicks: budget }};
                            }}

                            const seatsAreas = document.querySelectorAll('.seats-area');
                            for (let area of seatsAreas) {{
                                const activeSubPanel = area.querySelector('.v-expansion-panel--active');
                                if (activeSubPanel && activeSubPanel.querySelector('.mdi-plus')) {{
                                    const r = applyCount(activeSubPanel);
                                    if (r) {{
                                        console.log('Retry: stepper set in nested sub-panel', JSON.stringify(r));
                                        return {{ success: true, clicked: r.clicked, countBefore: r.before, countClicks: r.clicks }};
                                    }}
                                }}
                            }}

                            const panels = document.querySelectorAll('.v-expansion-panel');
                            for (let panel of panels) {{
                                if (panel.classList.contains('v-expansion-panel--active') &&
                                    panel.querySelector('.mdi-plus')) {{
                                    const r = applyCount(panel);
                                    if (r) {{
                                        console.log('Retry: stepper set in panel', JSON.stringify(r));
                                        return {{ success: true, clicked: r.clicked, countBefore: r.before, countClicks: r.clicks }};
                                    }}
                                }}
                            }}
                            return {{ success: false, clicked: false }};
                        }})();
                    ''')

                    retry_parsed = util.parse_nodriver_result(retry_result)
                    if isinstance(retry_parsed, dict):
                        if retry_parsed.get('clicked', False):
                            debug.log(f"[RETRY] Success on attempt {retry + 1}")
                            is_selected = True
                            break

                    await asyncio.sleep(0.2)

            if debug.enabled:
                if is_selected:
                    selected_type = result.get('type', '')
                    selected_name = result.get('selected', '')
                    debug.log(f"Selection successful - type: {selected_type}, item: {selected_name}")
                    row_text = result.get('rowText')
                    if row_text:
                        # Say which ticket row was taken. On events where a zone offers both a
                        # plain and a "+ perk" variant, this is the line that proves the right
                        # one was picked - the perk usually cannot be added after checkout.
                        mark = "PREFERRED" if result.get('rowPreferred') else "first available"
                        debug.log(f"[TICKET TYPE] Chose ({mark}) from {result.get('rowCount', '?')} row(s): {row_text}")
                elif result.get('strict_mode'):
                    kw = result.get('attempted_keyword') or area_keyword
                    if result.get('keyword_in_sold_out'):
                        debug.log(f"[STRICT] Target area '{kw}' is currently sold out (remaining 0); strict mode keeps refreshing for returns.")
                    else:
                        debug.log(f"[STRICT] No purchasable area matches '{kw}'; strict mode keeps refreshing.")
                    debug.log("[STRICT] To auto-fallback to other available areas, enable: Advanced Settings -> area_auto_fallback")
                else:
                    debug.log(f"Selection failed: {result.get('message', 'unknown error')}")
        else:
            debug.log(f"Unified selector returned invalid result: {result}")
            is_selected = False

    except Exception as exc:
        if debug.enabled:
            debug.log(f"Unified selector exception error: {exc}")
            debug.log(f"Exception type: {type(exc).__name__}")
            debug.log(f"Traceback: {traceback.format_exc()}")
        is_selected = False

    if not is_selected:
        try:
            debug.log("Checking page status to decide whether to continue...")

            # Ask the page for the real enable condition rather than inferring it from the
            # rendered ticket count, which silently ignores `guarantee` and the serial rule.
            status = await nodriver_ticketplus_read_next_step_state(tab)
            debug.log(
                f"[STATUS] source={status['source']} can_next={status['can_next']} "
                f"guarantee={status['guarantee']} has_ticket={status['has_ticket']} "
                f"serial_ok={status['serial_ok']} total={status['total_ticket']}"
            )

            if status["degraded"]:
                debug.log("[STATUS][DEGRADED] Could not read page state; treating selection as failed")
            elif status["can_next"]:
                debug.log("Page already satisfies the next-step condition, considered selection successful")
                is_selected = True
            elif status["has_ticket"] and status["guarantee"] is False:
                # Tickets are chosen but the agreement box is not ticked. Say so plainly:
                # this is the shape that leaves the button grey forever.
                debug.log("[STATUS] Tickets selected but agreement (guarantee) not accepted yet")

        except Exception as backup_exc:
            debug.log(f"Backup check failed: {backup_exc}")

    return is_selected


async def nodriver_ticketplus_click_next_button_unified(tab, config_dict):
    """TicketPlus unified next button clicker - layout_style independent."""
    debug = util.create_debug_logger(config_dict)

    debug.log("Unified next button clicker started")

    try:
        if await sleep_with_pause_check(tab, 0.6, config_dict):
            return False

        js_result = await asyncio.wait_for(tab.evaluate('''
            (function() {
                console.log('[NEXT BUTTON] Unified next button clicker started');

                function waitForButtonEnable(selector, maxWait = ''' + str(CONST_TICKETPLUS_BUTTON_WAIT_MS) + ''') {
                    return new Promise((resolve) => {
                        const startTime = Date.now();
                        const checkButton = () => {
                            const button = document.querySelector(selector);
                            if (button && !button.disabled && !button.classList.contains('v-btn--disabled') && !button.classList.contains('disabledBtn')) {
                                resolve(button);
                                return;
                            }

                            if (Date.now() - startTime < maxWait) {
                                setTimeout(checkButton, 100);
                            } else {
                                resolve(null);
                            }
                        };
                        checkButton();
                    });
                }
                // NOTE: this IIFE can return a Promise (the waitForButtonEnable branch
                // below), so the caller MUST pass await_promise=True. zendriver defaults it
                // to False, which hands Python an unresolved-promise stub instead of the
                // result object - the wait branch then always read as failure.

                // NOTE: ':contains()' is jQuery, NOT valid CSS. querySelector throws
                // SyntaxError on it, which used to blow up this whole IIFE and made the
                // waitForButtonEnable fallback below unreachable dead code. Text matching
                // is done explicitly instead.
                const buttonSelectors = [
                    'button.nextBtn:not(.disabledBtn):not(.v-btn--disabled)',
                    '.order-footer button.nextBtn:not(.disabledBtn)',
                    '.order-footer .v-btn--has-bg:not(.v-btn--disabled):not(.disabledBtn)',
                    '.nextBtn:not([disabled])'
                ];

                function isClickable(btn) {
                    return btn && !btn.disabled &&
                           !btn.classList.contains('v-btn--disabled') &&
                           !btn.classList.contains('disabledBtn');
                }

                let nextButton = null;
                for (let selector of buttonSelectors) {
                    let candidate = null;
                    try {
                        candidate = document.querySelector(selector);
                    } catch (selErr) {
                        console.log('[NEXT BUTTON] bad selector skipped:', selector, selErr.message);
                        continue;
                    }
                    if (isClickable(candidate)) {
                        nextButton = candidate;
                        console.log('[SUCCESS] Found enabled next button:', selector);
                        break;
                    }
                }

                // Text-based fallback (replaces the invalid :contains selectors).
                if (!nextButton) {
                    const byText = Array.from(document.querySelectorAll('button')).find(b => {
                        const t = (b.textContent || '').trim();
                        return (t.includes('下一步') || /next/i.test(t)) && isClickable(b);
                    });
                    if (byText) {
                        nextButton = byText;
                        console.log('[SUCCESS] Found enabled next button by text');
                    }
                }

                if (!nextButton) {
                    console.log('[WAITING] Waiting for next button to enable...');
                    return waitForButtonEnable('button.nextBtn, .nextBtn').then(button => {
                        if (button) {
                            console.log('[SUCCESS] Next button enabled');
                            button.click();
                            return {
                                success: true,
                                message: 'Next button clicked (after wait)',
                                buttonText: button.textContent.trim()
                            };
                        } else {
                            console.log('[ERROR] Next button still not found after wait');
                            return { success: false, message: 'Next button still not found after wait' };
                        }
                    });
                }

                nextButton.click();
                console.log('[SUCCESS] Next button clicked');

                return {
                    success: true,
                    message: 'Next button clicked',
                    buttonText: nextButton.textContent.trim()
                };
            })();
        ''', await_promise=True), timeout=CONST_TICKETPLUS_BUTTON_WAIT_TIMEOUT_SEC)

        result = util.parse_nodriver_result(js_result)
        if isinstance(result, dict):
            success = result.get('success', False)
            if debug.enabled:
                if success:
                    button_text = result.get('buttonText', '')
                    debug.log(f"[SUCCESS] Next button clicked successfully - Button text: {button_text}")
                else:
                    debug.log(f"[ERROR] Next button click failed: {result.get('message', 'Unknown error')}")
            return success

    except Exception as exc:
        debug.log(f"Unified next button click error: {exc}")

    return False


async def nodriver_ticketplus_ticket_agree(tab, config_dict):
    """TicketPlus agreement checkbox."""
    if await check_and_handle_pause(config_dict):
        return False

    debug = util.create_debug_logger(config_dict)
    is_finish_checkbox_click = False

    # Single round-trip instead of query_selector_all + 2-3 evaluate() calls per checkbox.
    # Already-checked boxes are skipped, so this is safe to call every cycle - which it now
    # is, because `guarantee` (the real gate on the next button) can be reset by any Vue
    # re-render and a one-shot tick would leave the button grey forever.
    try:
        js_result = await asyncio.wait_for(tab.evaluate('''
            (function() {
                var boxes = document.querySelectorAll('input[type="checkbox"]');
                var total = 0, already = 0, clicked = 0, forced = 0, failed = 0;
                for (var i = 0; i < boxes.length; i++) {
                    var box = boxes[i];
                    // Vuetify hides the real input behind a styled span, so offsetParent is
                    // null for legitimately interactive boxes; only skip explicitly hidden.
                    if (box.disabled) continue;
                    total++;
                    if (box.checked) { already++; continue; }
                    try {
                        box.click();
                    } catch (e) {}
                    if (box.checked) { clicked++; continue; }
                    try {
                        box.checked = true;
                        box.dispatchEvent(new Event('input', { bubbles: true }));
                        box.dispatchEvent(new Event('change', { bubbles: true }));
                    } catch (e) {}
                    if (box.checked) { forced++; } else { failed++; }
                }
                return JSON.stringify({ total: total, already: already, clicked: clicked,
                                        forced: forced, failed: failed });
            })();
        '''), timeout=5.0)
    except Exception as exc:
        debug.log("agreement checkbox pass failed:", exc)
        return False

    parsed = util.parse_nodriver_result(js_result)
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except Exception:
            parsed = None

    if isinstance(parsed, dict):
        total = parsed.get('total', 0)
        already = parsed.get('already', 0)
        clicked = parsed.get('clicked', 0)
        forced = parsed.get('forced', 0)
        failed = parsed.get('failed', 0)
        is_finish_checkbox_click = (already + clicked + forced) > 0
        debug.log(
            f"[AGREE] checkboxes={total} already={already} clicked={clicked} "
            f"forced={forced} failed={failed}"
        )
        if failed:
            debug.log("[AGREE] Some checkboxes refused to tick; next button may stay disabled")
    else:
        debug.log(f"[AGREE] Unexpected result: {parsed}")

    return is_finish_checkbox_click


async def nodriver_ticketplus_accept_realname_card(tab):
    """Dismiss the real-name / lottery notice dialog that blocks the activity page.

    The dialog is `v-dialog--persistent`, so it cannot be dismissed by clicking away, and
    it offers TWO buttons - the confirm one AND a "back to home" one. Clicking the wrong
    one navigates away from the event entirely, so the deny list below is not optional.

    The previous implementation relied on a six-level strict-child CSS chain ending in
    `button.primary`; that happened to pick the right button (the cancel button carries
    `primary--text`, a different class token) but broke on any wrapper change. Matching on
    the visible label is both safer and more durable.
    """
    is_button_clicked = False
    try:
        result = await asyncio.wait_for(tab.evaluate('''
            (function() {
                var ACCEPT = ['確定', '我知道了', '知道了', '同意', 'OK', 'Ok'];
                // Never click these: they navigate away or abandon the order.
                var DENY = ['回到首頁', '回首頁', '取消購票', '取消訂單', '不同意', '離開'];
                var dialogs = document.querySelectorAll('[role="dialog"], .v-dialog, .v-dialog__content');
                for (var i = 0; i < dialogs.length; i++) {
                    var dlg = dialogs[i];
                    if (dlg.offsetParent === null) continue;
                    var buttons = dlg.querySelectorAll('button');
                    for (var j = 0; j < buttons.length; j++) {
                        var btn = buttons[j];
                        var txt = (btn.textContent || '').replace(/\\s+/g, '');
                        if (!txt) continue;
                        if (DENY.some(function (d) { return txt.indexOf(d) >= 0; })) continue;
                        if (!ACCEPT.some(function (a) { return txt.indexOf(a) >= 0; })) continue;
                        if (btn.disabled) continue;
                        btn.click();
                        return JSON.stringify({ clicked: true, label: txt.slice(0, 30),
                                                title: (dlg.textContent || '').trim().slice(0, 40) });
                    }
                }
                return JSON.stringify({ clicked: false, label: '', title: '' });
            })();
        '''), timeout=3.0)

        parsed = util.parse_nodriver_result(result)
        if isinstance(parsed, str):
            try:
                parsed = json.loads(parsed)
            except Exception:
                parsed = None
        if isinstance(parsed, dict):
            is_button_clicked = bool(parsed.get('clicked'))
    except Exception:
        pass
    return is_button_clicked


async def nodriver_ticketplus_accept_other_activity(tab):
    """Accept other activity popup."""
    is_button_clicked = False
    try:
        button = await tab.query_selector('div[role="dialog"] > div.v-dialog > button.primary-1 > span > i.v-icon')
        if button:
            await button.click()
            is_button_clicked = True
    except Exception as exc:
        pass
    return is_button_clicked


async def nodriver_ticketplus_accept_order_fail(tab, debug=None):
    """Detect and dismiss order failure popup (e.g. "Purchase failed / Sold out").

    Uses text-driven detection: scans visible dialogs for failure keywords, then
    clicks any button whose label looks like a dismissal action. CSS selectors
    for Vuetify dialogs vary across versions, so text matching is more robust.

    Returns:
        True  -- failure popup detected (and dismissed if possible)
        False -- no failure popup found
        None  -- evaluate failed; popup state unknown (caller should skip order submission)
    """
    try:
        js_result = await tab.evaluate('''
            (function() {
                const failureTexts = [
                    '購票失敗',
                    '您選擇的票種已售完',
                    '已售完',
                    '別人搶先一步',
                    '已無可配座位',
                    '本活動有限制購票總張數',
                    '已被購買',
                    '系統忙碌',
                    '無法購票'
                ];
                // Safety net: the exact wording above is unverified against every failure
                // dialog TicketPlus can raise. A dialog carrying any of these fragments is
                // treated as a failure too, so an unseen phrasing cannot leave the popup
                // sitting on top of the page blocking every later click.
                // NOTE: no '逾時' here on purpose - the seat-hold countdown dialog uses that word,
                // and treating it as a purchase failure would reload the page mid-hold.
                const failureFragments = ['失敗', '售完', '無法', '已被', '忙碌', '搶先', '額滿'];
                const buttonTexts = [
                    '我知道了',
                    '知道了',
                    '確定',
                    'OK',
                    'Ok'
                ];
                const dialogs = document.querySelectorAll('[role="dialog"], .v-dialog, .v-dialog__content');
                for (const dialog of dialogs) {
                    if (dialog.offsetParent === null) continue;
                    const text = (dialog.textContent || '').trim();
                    const exact = failureTexts.some(t => text.includes(t));
                    const loose = failureFragments.some(t => text.includes(t));
                    if (!exact && !loose) continue;
                    const buttons = dialog.querySelectorAll('button');
                    for (const btn of buttons) {
                        const btnText = (btn.textContent || '').trim();
                        if (buttonTexts.some(t => btnText.includes(t))) {
                            btn.click();
                            return { foundFailure: true, buttonClicked: true, exactMatch: exact, dialogText: text.slice(0, 80) };
                        }
                    }
                    return { foundFailure: true, buttonClicked: false, exactMatch: exact, dialogText: text.slice(0, 80) };
                }
                return { foundFailure: false, buttonClicked: false, exactMatch: false, dialogText: '' };
            })();
        ''')

        # zendriver can hand back the [['key', {'type':..,'value':..}], ...] shape instead
        # of a plain dict. Every other evaluate() in this file normalises through
        # parse_nodriver_result; this one used to skip it, so a list-shaped reply was read
        # as "no popup" and the dialog stayed on top of the page blocking all later clicks.
        js_result = util.parse_nodriver_result(js_result)

        if isinstance(js_result, dict) and js_result.get('foundFailure'):
            if debug is not None:
                debug.log(f"[ORDER FAIL] Detected popup: {js_result.get('dialogText', '')}")
                if not js_result.get('exactMatch', True):
                    debug.log("[ORDER FAIL] Matched by loose fragment - please report this dialog text")
                if js_result.get('buttonClicked'):
                    debug.log("[ORDER FAIL] Dismissed via dialog button")
                else:
                    debug.log("[ORDER FAIL] Dismiss button not found in dialog")
            return True
        return False
    except Exception as exc:
        if debug is not None:
            debug.log(f"[ORDER FAIL][DEGRADED] evaluate failed, popup state unknown: {exc}")
        return None


async def nodriver_ticketplus_check_queue_status(tab, config_dict, force_show_debug=False):
    """Check queue status - optimized to avoid duplicate output."""
    debug = util.create_debug_logger(enabled=(config_dict.get("advanced", {}).get("verbose", False) or force_show_debug))

    try:
        result = await tab.evaluate('''
            (function() {
                const queueKeywords = [
                    '\u6392\u968a\u8cfc\u7968\u4e2d',
                    '\u8acb\u7a0d\u5019',
                    '\u8acb\u5225\u96e2\u958b\u9801\u9762',
                    '\u8acb\u52ff\u96e2\u958b',
                    '\u8acb\u52ff\u95dc\u9589\u7db2\u9801',
                    '\u540c\u6642\u4f7f\u7528\u591a\u500b\u88dd\u7f6e',
                    '\u8996\u7a97\u8cfc\u7968',
                    '\u6b63\u5728\u8655\u7406',
                    '\u8655\u7406\u4e2d'
                ];

                const bodyText = document.body.textContent || '';

                const hasQueueKeyword = queueKeywords.some(keyword => bodyText.includes(keyword));

                const overlayScrim = document.querySelector('.v-overlay__scrim');
                const hasOverlay = overlayScrim && overlayScrim.style.opacity === '1';

                const dialogText = document.querySelector('.v-dialog')?.textContent || '';
                const hasQueueDialog = dialogText.includes('\u6392\u968a') ||
                                       dialogText.includes('\u8acb\u7a0d\u5019');

                const foundKeywords = queueKeywords.filter(keyword => bodyText.includes(keyword));

                return {
                    inQueue: hasQueueKeyword || hasOverlay || hasQueueDialog,
                    queueTitle: '',
                    foundKeywords: foundKeywords,
                    hasOverlay: hasOverlay,
                    hasQueueDialog: hasQueueDialog,
                    dialogText: hasQueueDialog ? dialogText.trim() : ''
                };
            })();
        ''')

        result = util.parse_nodriver_result(result)

        if isinstance(result, dict):
            is_in_queue = result.get('inQueue', False)
            if is_in_queue and force_show_debug:
                debug.log("[QUEUE] Queue status detected")
                if result.get('hasOverlay'):
                    debug.log("   Overlay scrim found (v-overlay__scrim)")
                if result.get('hasQueueDialog'):
                    debug.log(f"   Dialog content: {result.get('dialogText', '')}")
                if result.get('foundKeywords'):
                    keywords = result.get('foundKeywords', [])
                    if keywords and isinstance(keywords[0], dict):
                        keywords = [str(k.get('value', k)) for k in keywords]
                    elif keywords:
                        keywords = [str(k) for k in keywords]
                    if keywords:
                        debug.log(f"   Keywords found: {', '.join(keywords)}")
            return is_in_queue

        return False

    except Exception as exc:
        debug.log(f"Queue status check error: {exc}")
        return False


async def nodriver_ticketplus_confirm(tab, config_dict):
    """Seat-confirmation step (step 2 "select seat" / step 3 "confirm details").

    This is where the "I have read and agree to the member terms and privacy policy"
    checkbox actually lives - NOT on the ticket-area page - and the advance button stays
    disabled until it is ticked.

    Two changes over the previous version:
      * The advance button is found by its visible label, with an explicit deny list.
        The old `button.v-btn.primary` lookup takes the FIRST match in document order,
        which on this page can be a different primary-styled button entirely.
      * The click is no longer gated on the checkbox pass reporting success. A page with
        no checkbox at all is legitimate, and gating on it meant never advancing there.
    """
    await nodriver_ticketplus_ticket_agree(tab, config_dict)

    debug = util.create_debug_logger(config_dict)
    is_confirm_clicked = False

    try:
        result = await asyncio.wait_for(tab.evaluate('''
            (function() {
                var ADVANCE = ['下一步', '確定', '確認', '送出', 'Next', 'Confirm', 'Submit'];
                // Abandoning the order or leaving the flow must never be auto-clicked.
                var DENY = ['取消', '上一步', '回到首頁', '回首頁', '重新選', '放棄', 'Cancel', 'Back'];

                function usable(btn) {
                    return btn && !btn.disabled &&
                           !btn.classList.contains('v-btn--disabled') &&
                           !btn.classList.contains('disabledBtn') &&
                           btn.offsetParent !== null;
                }

                var seen = [];
                var buttons = document.querySelectorAll('button');
                for (var i = 0; i < buttons.length; i++) {
                    var btn = buttons[i];
                    var txt = (btn.textContent || '').replace(/\\s+/g, '');
                    if (!txt) continue;
                    seen.push(txt.slice(0, 12) + (usable(btn) ? '' : '(disabled)'));
                    if (DENY.some(function (d) { return txt.indexOf(d) >= 0; })) continue;
                    if (!ADVANCE.some(function (a) { return txt.indexOf(a) >= 0; })) continue;
                    if (!usable(btn)) continue;
                    btn.click();
                    return JSON.stringify({ clicked: true, label: txt.slice(0, 20), buttons: seen });
                }
                return JSON.stringify({ clicked: false, label: '', buttons: seen });
            })();
        '''), timeout=3.0)

        parsed = util.parse_nodriver_result(result)
        if isinstance(parsed, str):
            try:
                parsed = json.loads(parsed)
            except Exception:
                parsed = None

        if isinstance(parsed, dict):
            is_confirm_clicked = bool(parsed.get("clicked"))
            if is_confirm_clicked:
                debug.log(f"[CONFIRM] Clicked advance button: {parsed.get('label')}")
            else:
                debug.log(f"[CONFIRM] No enabled advance button. Buttons seen: {parsed.get('buttons')}")
    except Exception as exc:
        debug.log(f"[CONFIRM] Advance click failed: {exc}")

    return is_confirm_clicked


async def nodriver_ticketplus_order(tab, config_dict, ocr, Captcha_Browser):
    """TicketPlus order processing - supports three layout detection modes.

    Modifies _state in place (no return value).
    """
    debug = util.create_debug_logger(config_dict)

    if _state.get("is_ticket_assigned", False):
        debug.log("Ticket selection completed, skipping duplicate execution")
        return

    debug.log("=== TicketPlus Auto Layout Detection Started ===")

    # Queue gate. While the site has us in its purchase queue, pressing "next" again calls
    # beforeNext() -> enquene() and gets a FRESH queue ticket, i.e. it sends us to the back
    # of the line. The main loop re-enters this handler continuously, so without this gate
    # the bot re-queues itself every few seconds and can never reach the front - the page
    # sits on "queueing" forever while a human doing nothing would simply advance.
    #
    # Fail-open on purpose, unlike the reload gate: reloading while queued is destructive,
    # so that gate assumes "queued" when the page is unreadable. Here the opposite risk
    # applies - assuming "queued" on every failed read would freeze the bot permanently -
    # so a POSITIVE queue signal is required before skipping the cycle.
    queue_state = await nodriver_ticketplus_read_queue_state(tab)
    if queue_state["in_queue"] and not queue_state["degraded"]:
        _state["queue_since"] = _state.get("queue_since") or time.time()
        waited = time.time() - _state["queue_since"]
        debug.log(
            f"[QUEUE] Holding position ({queue_state['source']}, {waited:.0f}s). "
            "Not selecting or submitting - a resubmit would re-enter the queue at the back."
        )
        return
    if _state.get("queue_since"):
        debug.log(f"[QUEUE] Left the queue after {time.time() - _state['queue_since']:.0f}s")
        _state["queue_since"] = None

    if await sleep_with_pause_check(tab, 0.05, config_dict):
        debug.log("Paused during page wait")
        return

    layout_info = await nodriver_ticketplus_detect_layout_style(tab, config_dict)

    if layout_info and layout_info.get('paused'):
        debug.log("Paused during layout detection")
        return

    current_layout_style = layout_info.get('style', 0) if isinstance(layout_info, dict) else 0

    if debug.enabled:
        layout_names = {1: "Expansion panel (Page4)", 2: "Seat selection (Page2)", 3: "Simplified (Page1/Page3)"}
        button_status = "Enabled" if layout_info.get('button_enabled', False) else "Disabled"
        debug.log(f"Detected layout style: {current_layout_style} - {layout_names.get(current_layout_style, 'Unknown')}")
        debug.log(f"Layout detection details: Button found={layout_info.get('found', False)}, Button status={button_status}")
        if layout_info.get('debug_info'):
            debug.log(f"Layout detection debug: {layout_info.get('debug_info')}")

    is_button_enabled = await nodriver_ticketplus_check_next_button(tab)

    debug.log(f"Next button status: {'Enabled' if is_button_enabled else 'Disabled'}")

    is_price_assign_by_bot = False

    area_keyword_raw = config_dict.get("area_auto_select", {}).get("area_keyword", "").strip()

    keyword_array = util.parse_keyword_string_to_array(area_keyword_raw)

    debug.log(f"[TicketPlus] Parsed keywords: {keyword_array}")
    debug.log(f"[TicketPlus] Total keyword groups: {len(keyword_array)}")

    need_select_ticket = True

    debug.log(f"Ticket selection is always required (TicketPlus quirk)")

    is_price_assign_by_bot = False
    keyword_matched = False

    if len(keyword_array) > 0:
        for keyword_index, area_keyword_item in enumerate(keyword_array):
            debug.log(f"[TicketPlus AREA KEYWORD] Trying keyword #{keyword_index + 1}/{len(keyword_array)}: '{area_keyword_item}'")

            is_price_assign_by_bot = await nodriver_ticketplus_unified_select(tab, config_dict, area_keyword_item)

            if is_price_assign_by_bot:
                keyword_matched = True
                debug.log(f"[TicketPlus AREA KEYWORD] Keyword #{keyword_index + 1} matched: '{area_keyword_item}' [OK]")
                break

            debug.log(f"[TicketPlus AREA KEYWORD] Keyword #{keyword_index + 1} failed, trying next...")

        if not keyword_matched:
            debug.log(f"[TicketPlus AREA KEYWORD] All {len(keyword_array)} keywords failed to match")
    else:
        debug.log(f"[TicketPlus AREA KEYWORD] No keyword specified, using auto select mode")
        is_price_assign_by_bot = await nodriver_ticketplus_unified_select(tab, config_dict, "")

    is_need_refresh = not is_price_assign_by_bot

    if is_price_assign_by_bot:
        if await check_and_handle_pause(config_dict):
            return

        debug.log("Ticket selection successful, processing discount code and submit")

        is_answer_sent, _state["fail_list"], is_question_popup = await nodriver_ticketplus_order_exclusive_code(tab, config_dict, _state["fail_list"])

        if await sleep_with_pause_check(tab, 0.3, config_dict):
            debug.log("Paused before form submission")
            return
        await nodriver_ticketplus_ticket_agree(tab, config_dict)

        # Verify the real enable condition before pressing. If `guarantee` is still false
        # the button is grey and the click is a no-op, so re-tick and re-check once.
        pre_submit = await nodriver_ticketplus_read_next_step_state(tab)
        if pre_submit["source"] == "vue" and pre_submit["can_next"] is False:
            debug.log(
                f"[PRE-SUBMIT] canNextStep=False (guarantee={pre_submit['guarantee']}, "
                f"has_ticket={pre_submit['has_ticket']}, serial_ok={pre_submit['serial_ok']})"
            )
            if pre_submit["guarantee"] is False:
                debug.log("[PRE-SUBMIT] Re-ticking agreement checkbox")
                await nodriver_ticketplus_ticket_agree(tab, config_dict)
                pre_submit = await nodriver_ticketplus_read_next_step_state(tab)
                debug.log(f"[PRE-SUBMIT] After re-tick: canNextStep={pre_submit['can_next']}")
            if pre_submit["serial_ok"] is False:
                debug.log(
                    "[PRE-SUBMIT] This session requires a serial/member code and none is filled. "
                    "Set it in Advanced Settings -> discount_code."
                )

        url_before_submit = _ticketplus_current_url(tab)

        # Reload guard, layer A: the main loop re-enters this handler every cycle, so
        # without a time guard a submit whose response has not come back yet would be
        # pressed again on the very next pass. Layer B (URL moved) clears it immediately.
        now = time.time()
        last_submit_at = _state.get("last_submit_at", 0)
        last_submit_url = _state.get("last_submit_url", "")
        within_guard = (
            last_submit_url == url_before_submit
            and (now - last_submit_at) < CONST_TICKETPLUS_SUBMIT_GUARD_SEC
        )
        if within_guard:
            remaining = CONST_TICKETPLUS_SUBMIT_GUARD_SEC - (now - last_submit_at)
            debug.log(f"[SUBMIT] Guard active ({remaining:.1f}s left) - previous submit may still be in flight")
            return

        _state["last_submit_at"] = now
        _state["last_submit_url"] = url_before_submit
        is_form_submitted = await nodriver_ticketplus_click_next_button_unified(tab, config_dict)

        if is_form_submitted:
            # Reload guard layer B: release as soon as the URL moves instead of sleeping a
            # flat 5-10s. A successful submit used to cost that whole sleep for nothing.
            navigated = await _ticketplus_wait_for_navigation(
                tab, url_before_submit, CONST_TICKETPLUS_SUBMIT_WAIT_SEC, config_dict, debug
            )

            if not navigated:
                # Still on the same page. Either queued, or the press did not take.
                queue_state = await nodriver_ticketplus_read_queue_state(tab)
                if queue_state["in_queue"]:
                    # Do NOT spin here. Blocking inside the platform handler starves the
                    # main loop, which is where the stop flag, the pause flag and config
                    # hot-reload are checked - the bot became unstoppable while queued.
                    _state["queue_since"] = _state.get("queue_since") or time.time()
                    waited = time.time() - _state["queue_since"]
                    debug.log(
                        f"[QUEUE] In queue via {queue_state['source']} ({waited:.0f}s so far). "
                        "Yielding to main loop; will re-check next cycle."
                    )
                else:
                    _state["queue_since"] = None
                    debug.log("[SUBMIT] URL unchanged and not queued - will re-check next cycle")
            else:
                # Layer B: navigation happened, so the submit is definitively done. Release
                # the guard immediately instead of waiting out the timer.
                _state["queue_since"] = None
                _state["last_submit_at"] = 0
                _state["last_submit_url"] = ""

        debug.log(f"Form submission: {'Success' if is_form_submitted else 'Failed'}")

        if not is_form_submitted:
            # Pattern A escape hatch: the completeness check can never cover conditions the
            # site adds later, so when every field is satisfied but the page has not moved,
            # press again (throttled; a disabled button makes this a harmless no-op).
            post = await nodriver_ticketplus_read_next_step_state(tab)
            now = time.time()
            last_press = _state.get("last_repress_at", 0)
            if post["can_next"] and (now - last_press) >= CONST_TICKETPLUS_REPRESS_COOLDOWN_SEC:
                _state["last_repress_at"] = now
                debug.log("[REPRESS] Fields complete but still on the order page - pressing next again")
                await nodriver_ticketplus_click_next_button_unified(tab, config_dict)
    else:
        debug.log("Ticket selection failed, cannot continue")

        auto_reload_interval = config_dict["advanced"].get("auto_reload_page_interval", 0)
        if auto_reload_interval >= 0:
            if auto_reload_interval > 0:
                debug.log(f"[AUTO RELOAD] Waiting {auto_reload_interval} seconds before reload...")
                await asyncio.sleep(auto_reload_interval)

            # A full reload while queued throws the queue position away and the bot then
            # re-queues from the back, forever. TicketPlus hides the partial-refresh
            # float-btn while isPending, so "button not found" used to fall straight
            # through to tab.reload() exactly when reloading was most destructive.
            queue_state = await nodriver_ticketplus_read_queue_state(tab)
            if queue_state["in_queue"]:
                debug.log(
                    f"[AUTO RELOAD] Skipped - in queue (source: {queue_state['source']}). "
                    "The site retries enqueue on its own; reloading would lose the slot."
                )
            else:
                debug.log("[AUTO RELOAD] Refreshing ticket count...")
                try:
                    clicked = await _ticketplus_click_refresh_button(tab, debug)
                    if not clicked:
                        await tab.reload()
                        debug.log("[AUTO RELOAD] Full page reload (button not found)")
                except Exception as reload_exc:
                    debug.log(f"[AUTO RELOAD] Reload failed: {reload_exc}")

    debug.log("=== TicketPlus Simplified Booking Ended ===")


async def nodriver_ticketplus_wait_for_vue_ready(tab, max_wait_ms=800):
    """Wait for Vue.js ticket area elements to render (dynamic detection).

    Args:
        tab: NoDriver tab
        max_wait_ms: Maximum wait time in milliseconds, default 800ms

    Returns:
        bool: True if Vue.js is ready, False if timed out
    """
    try:
        await asyncio.sleep(0.15)

        result = await tab.evaluate(f'''
            (function() {{
                return new Promise((resolve) => {{
                    const startTime = Date.now();
                    const maxWait = {max_wait_ms};

                    const check = () => {{
                        const selectors = [
                            '.v-expansion-panel-header',
                            '.order-content .v-btn',
                            'button.nextBtn',
                            '.ticket-list button'
                        ];

                        let hasContent = false;
                        for (const selector of selectors) {{
                            const elements = document.querySelectorAll(selector);
                            if (elements.length > 0) {{
                                hasContent = Array.from(elements).some(el => {{
                                    const text = el.textContent || '';
                                    return text.includes('NT') ||
                                           text.includes('\u5269\u9918') ||
                                           text.includes('\u71b1\u8ce3') ||
                                           text.includes('\u4e0b\u4e00\u6b65') ||
                                           text.includes('\u552e\u5b8c');
                                }});
                                if (hasContent) break;
                            }}
                        }}

                        if (hasContent) {{
                            resolve({{ ready: true, elapsed: Date.now() - startTime }});
                        }} else if (Date.now() - startTime < maxWait) {{
                            setTimeout(check, 30);
                        }} else {{
                            resolve({{ ready: false, elapsed: maxWait }});
                        }}
                    }};

                    check();
                }});
            }})();
        ''', await_promise=True)

        result = util.parse_nodriver_result(result)
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except Exception:
                pass

        if isinstance(result, dict):
            return result.get('ready', False)
        return False

    except Exception as exc:
        return False


async def nodriver_ticketplus_check_next_button(tab):
    """Check if next button is enabled."""
    try:
        result = await tab.evaluate('''
            (function() {
                const selectors = [
                    "div.order-footer button.nextBtn",
                    "button.nextBtn",
                    "button[class*='next']",
                    ".order-footer .nextBtn"
                ];

                for (let selector of selectors) {
                    const btn = document.querySelector(selector);
                    if (btn) {
                        return {
                            found: true,
                            enabled: !btn.disabled && !btn.classList.contains('disabledBtn')
                        };
                    }
                }

                return { found: false, enabled: false };
            })();
        ''')

        result = util.parse_nodriver_result(result)
        return result.get('enabled', False) if isinstance(result, dict) else False

    except Exception as exc:
        return False


async def nodriver_ticketplus_order_exclusive_code(tab, config_dict, fail_list):
    """Handle exclusive discount codes."""
    debug = util.create_debug_logger(config_dict)

    if await check_and_handle_pause(config_dict):
        return False, fail_list, False

    discount_code = config_dict["advanced"].get("discount_code", "").strip()

    if not discount_code:
        debug.log("[DISCOUNT CODE] No discount code configured, skipping")
        return False, fail_list, False

    debug.log(f"[DISCOUNT CODE] Attempting to fill discount code: {discount_code}")

    try:
        escaped_discount_code = discount_code.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r")

        result = await tab.evaluate(f'''
            (function() {{
                const keywords = ['\u5e8f\u865f', '\u52a0\u8cfc', '\u512a\u60e0'];
                const discountCode = '{escaped_discount_code}';
                let filledCount = 0;

                const labelDivs = document.querySelectorAll('.exclusive-code .label');
                for (let label of labelDivs) {{
                    const labelText = label.textContent.trim();
                    const container = label.closest('.exclusive-code');
                    if (!container) continue;

                    const input = container.querySelector('.v-text-field__slot input[type="text"]');

                    const hasKeyword = keywords.some(keyword => labelText.includes(keyword));
                    if (hasKeyword && input && !input.value) {{
                        input.value = discountCode;
                        input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        filledCount++;
                    }}
                }}

                return {{
                    success: filledCount > 0,
                    filledCount: filledCount
                }};
            }})()
        ''')

        if result:
            if isinstance(result, dict):
                success = result.get('success', False)
                filled_count = result.get('filledCount', 0)
            else:
                debug.log(f"[DISCOUNT CODE] Unexpected result type: {type(result)}, value: {result}")
                success = True
                filled_count = 1

            if success and filled_count > 0:
                debug.log(f"[DISCOUNT CODE] Successfully filled {filled_count} discount code field(s)")
                return True, fail_list, False

        debug.log("[DISCOUNT CODE] No matching discount code fields found on page")
        return False, fail_list, False

    except Exception as e:
        debug.log(f"[DISCOUNT CODE] Error filling discount code: {str(e)}")
        return False, fail_list, False


async def nodriver_ticketplus_main(tab, url, config_dict, ocr, Captcha_Browser):
    """TicketPlus main entry point.

    Thin guard around the real handler. The main loop in nodriver_tixcraft.py calls this
    from inside `while True:` with no try/except anywhere between here and
    `asyncio.run(main(args))`, so ANY exception escaping this function kills the whole bot
    process mid-purchase. Several awaits on the purchase path can genuinely raise:
    `tab.sleep()` performs a CDP `Target.getTargetInfo` round-trip before sleeping, which
    throws when the websocket hiccups or the target closes during navigation.

    Swallowing here is the right trade-off: one lost cycle is recoverable (the main loop
    re-enters ~20x/second), a dead process is not. Failures are always surfaced.

    Returns:
        dict: {"purchase_completed": bool, "is_ticket_assigned": bool}
    """
    try:
        return await _nodriver_ticketplus_main_impl(tab, url, config_dict, ocr, Captcha_Browser)
    except asyncio.CancelledError:
        # Never swallow cancellation - that is the shutdown path.
        raise
    except Exception as exc:
        debug = util.create_debug_logger(config_dict)
        # print() rather than debug.log(): the user must see this even with verbose off,
        # because a repeating line here means the bot is looping without progressing.
        print(f"[TICKETPLUS ERROR] Cycle aborted: {type(exc).__name__}: {exc}")
        debug.log(f"[TICKETPLUS ERROR] Traceback: {traceback.format_exc()}")
        return _get_status()


async def _nodriver_ticketplus_main_impl(tab, url, config_dict, ocr, Captcha_Browser):
    """Real TicketPlus entry point. Call via nodriver_ticketplus_main (exception guard)."""
    if await check_and_handle_pause(config_dict):
        return _get_status()

    debug = util.create_debug_logger(config_dict)

    if not _state:
        _state["fail_list"] = []
        _state["is_popup_confirm"] = False
        _state["is_ticket_assigned"] = False
        _state["start_time"] = None
        _state["done_time"] = None
        _state["elapsed_time"] = None
        _state["signin_form_filled"] = False
        _state["purchase_completed"] = False
        _state["queue_since"] = None
        _state["last_repress_at"] = 0
        _state["last_submit_at"] = 0
        _state["last_submit_url"] = ""

    home_url = 'https://ticketplus.com.tw/'
    is_user_signin = False
    if home_url == url.lower():
        if config_dict["ocr_captcha"]["enable"]:
            domain_name = url.split('/')[2]
            if not Captcha_Browser is None:
                Captcha_Browser.set_domain(domain_name)

        is_user_signin = await nodriver_ticketplus_account_auto_fill(tab, config_dict)

    if is_user_signin:
        config_homepage = config_dict["homepage"].lower().rstrip('/')
        is_homepage_target = config_homepage in ['https://ticketplus.com.tw', 'ticketplus.com.tw']
        if not is_homepage_target and url.lower() != config_dict["homepage"].lower():
            try:
                await tab.get(config_dict["homepage"])
            except Exception as e:
                pass

    # https://ticketplus.com.tw/activity/XXX
    if '/activity/' in url.lower():
        is_event_page = False
        if _ticketplus_path_segment_count(url)==5:
            is_event_page = True

        if is_event_page:
            _state["is_popup_confirm"] = False
            _state["order_page_visited"] = False

            is_button_pressed = await nodriver_ticketplus_accept_realname_card(tab)
            debug.log(f"[TICKETPLUS] Realname Card: {is_button_pressed}")

            is_button_pressed = await nodriver_ticketplus_accept_other_activity(tab)
            debug.log(f"[TICKETPLUS] Other Activity: {is_button_pressed}")

            if config_dict["date_auto_select"]["enable"]:
                await nodriver_ticketplus_date_auto_select(tab, config_dict)

    # https://ticketplus.com.tw/order/XXX/OOO
    if '/order/' in url.lower():
        is_event_page = False
        if _ticketplus_path_segment_count(url)==6:
            is_event_page = True

        if is_event_page:
            _state["start_time"] = time.time()

            # Being on /order/ means we are back at ticket selection, whatever happened
            # before. The flag used to clear only when the URL left /order/ entirely, so a
            # bounce back from /confirm/ (real-name form times out after 10 minutes, or the
            # order fails) left it stuck True and nodriver_ticketplus_order returned
            # immediately forever - the submit lives inside the block it skips.
            if _state.get("is_ticket_assigned", False):
                debug.log("[STATE] Back on /order/ - clearing is_ticket_assigned so selection can resume")
                _state["is_ticket_assigned"] = False
                _state["is_popup_confirm"] = False

            is_first_visit = not _state.get("order_page_visited", False)
            if is_first_visit:
                max_wait = 2000
                fallback_delay = 0.5
                _state["order_page_visited"] = True
            else:
                max_wait = 1000
                fallback_delay = 0.3

            if debug.enabled:
                visit_type = "First visit" if is_first_visit else "Reload"
                debug.log(f"[VUE INIT] {visit_type}, dynamic detection (max {max_wait}ms)...")

            is_ready = await nodriver_ticketplus_wait_for_vue_ready(tab, max_wait_ms=max_wait)

            debug.log(f"[VUE INIT] Vue.js ready: {is_ready}")

            if not is_ready:
                await asyncio.sleep(fallback_delay)

            is_button_pressed = await nodriver_ticketplus_accept_realname_card(tab)
            is_order_fail_handled = await nodriver_ticketplus_accept_order_fail(tab, debug)

            if is_order_fail_handled is True:
                # The submit is settled (it failed), so the in-flight guard must come off.
                # Forgetting this is a known trap: the guard would keep blocking the retry
                # and the bot would sit idle after every sold-out popup.
                _state["last_submit_at"] = 0
                _state["last_submit_url"] = ""

                # Same rule as the auto-reload path: never reload while queued.
                queue_state = await nodriver_ticketplus_read_queue_state(tab)
                if queue_state["in_queue"]:
                    debug.log(
                        f"[ORDER FAIL] Popup dismissed but still queued (source: "
                        f"{queue_state['source']}); holding position instead of reloading."
                    )
                else:
                    debug.log("[ORDER FAIL] Reloading page to refresh ticket availability")
                    try:
                        await tab.reload()
                        await asyncio.sleep(0.5)
                    except Exception as reload_exc:
                        debug.log(f"[ORDER FAIL] Reload failed: {reload_exc}")
                    _state["order_page_visited"] = False
                return _get_status()
            elif is_order_fail_handled is None:
                debug.log("[ORDER FAIL][DEGRADED] Detection unavailable, skipping order submission this cycle")
                return _get_status()

            await nodriver_ticketplus_order(tab, config_dict, ocr, Captcha_Browser)

    else:
        _state["fail_list"] = []
        _state["is_ticket_assigned"] = False
        _state["start_time"] = None

    # https://ticketplus.com.tw/confirm/xx/oo
    # https://ticketplus.com.tw/confirmseat/xx/oo
    if '/confirm/' in url.lower() or '/confirmseat/' in url.lower():
        is_event_page = False
        if _ticketplus_path_segment_count(url)==6:
            is_event_page = True

        if is_event_page:
            _state["is_ticket_assigned"] = True

            if not _state["is_popup_confirm"]:
                _state["is_popup_confirm"] = True

                if _state["start_time"]:
                    _state["done_time"] = time.time()
                    _state["elapsed_time"] = _state["done_time"] - _state["start_time"]
                    debug.log(f"[TICKETPLUS] NoDriver TicketPlus booking time: {_state['elapsed_time']:.3f} seconds")

                debug.log("[TICKETPLUS] Entered confirmation page, booking successful")

                if config_dict["advanced"]["play_sound"]["order"]:
                    play_sound_while_ordering(config_dict)
                send_discord_notification(config_dict, "order", "TicketPlus")
                send_telegram_notification(config_dict, "order", "TicketPlus")

                try:
                    await nodriver_ticketplus_confirm(tab, config_dict)
                    debug.log("[TICKETPLUS] Confirmation page processing completed")
                except Exception as exc:
                    debug.log(f"[TICKETPLUS] Confirmation page processing error: {exc}")

            _state["purchase_completed"] = True
        else:
            _state["is_popup_confirm"] = False
    else:
        _state["is_popup_confirm"] = False

    return _get_status()
