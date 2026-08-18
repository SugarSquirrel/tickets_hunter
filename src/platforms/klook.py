#!/usr/bin/env python3
#encoding=utf-8
"""platforms/klook.py -- Klook platform (klook.com).

Scope note: this module deliberately stops after the seat-assignment dialog is
confirmed. Filling in the real-name details and paying are left to the user - those
screens are not time-critical (Klook allows minutes there, versus roughly one minute to
accept an assigned seat) and they are the part with the least verified structure.
"""

import asyncio
import json
import time
import traceback

import util
from nodriver_common import (
    check_and_handle_pause,
    play_sound_while_ordering,
    send_discord_notification,
    send_telegram_notification,
)


__all__ = [
    "nodriver_klook_main",
    "nodriver_klook_read_state",
    "nodriver_klook_select_options",
    "nodriver_klook_set_quantity",
    "nodriver_klook_press_next",
    "nodriver_klook_confirm_seats",
    "nodriver_klook_read_seat_dialog",
    "nodriver_klook_dismiss_timeout",
    "nodriver_klook_paused_main",
]

# The booking widget mounts asynchronously; give it this long before deciding the page has
# nothing to offer.
CONST_KLOOK_WIDGET_WAIT_SEC = 6.0

# Minimum gap between two "next" presses on the same page, so a slow response cannot turn
# into a burst of submissions.
CONST_KLOOK_PRESS_GUARD_SEC = 3.0

# How long the seat-assignment dialog is left alone before the bot presses the confirm
# button itself. Klook holds the assigned seats for about a minute, and the person watching
# may want to look at what they got before accepting - so this is short enough to leave the
# hold intact, long enough to be a real decision window.
CONST_KLOOK_SEAT_CONFIRM_DELAY_SEC = 45.0

# The countdown above measures time the bot was actually running, accumulated cycle by
# cycle. A gap wider than this means it was not looping, so that time is not counted - the
# loop period here is well under a second, and anything past this is a pause or a stall.
CONST_KLOOK_SEAT_CYCLE_CAP_SEC = 10.0

# When the hold countdown printed in the seat modal gets this low, the confirm
# button is pressed no matter how long the decision window still had to run. The
# window is worth having only while it cannot cost the seats.
CONST_KLOOK_SEAT_SAFETY_SEC = 12

_state = {}


def _get_status():
    return {
        "seats_confirmed": _state.get("seats_confirmed", False),
        "handed_over": _state.get("handed_over", False),
    }


def _keyword_groups(config_dict):
    """Priority list from the area keyword box.

    Same shape as every other platform here: ';' separates priorities (tried in order),
    whitespace inside one priority is AND. Klook needs the AND part more than most - a
    BIGBANG option has to be pinned down by both its package and its seat tier.
    """
    raw = config_dict.get("area_auto_select", {}).get("area_keyword", "") or ""
    groups = util.parse_keyword_string_to_array(raw.strip())
    if not groups:
        groups = [g.strip() for g in raw.replace(",", ";").split(";") if g.strip()]
    return [g for g in groups if isinstance(g, str) and g.strip()]


def _exclude_terms(config_dict):
    raw = config_dict.get("keyword_exclude", "") or ""
    terms = util.parse_keyword_string_to_array(raw.strip())
    if not terms:
        terms = [t.strip() for t in raw.replace(",", ";").split(";") if t.strip()]
    return [t for t in terms if isinstance(t, str) and t.strip()]


# Class names below carry a build hash (skuGroup-hk2pfU and friends). Checked across seven
# saved pages from four different events and several days: every hash was identical, so
# they are build-time constants rather than per-render values. They will still change the
# day Klook ships a new frontend, so each lookup falls back to structure and visible text.
CONST_KLOOK_JS_HELPERS = r'''
    function norm(s) {
        return (s || '')
            .replace(/,/g, '')
            .replace(/\uff08/g, '(').replace(/\uff09/g, ')')
            .replace(/NT\$|NT\s*\$|\$/g, '')
            .replace(/\s+/g, ' ')
            .trim();
    }

    function textOf(el) { return norm(el ? (el.textContent || '') : ''); }

    // Every option group ("date", "time", "ticket type", and whatever a package event adds)
    // rendered as {label, options[]}. Falls back to finding the groups by their heading text
    // when the hashed classes stop matching.
    function readGroups() {
        var root = document.querySelector('.package-wrapper') || document;
        var groups = [];
        var blocks = root.querySelectorAll('[class*="skuGroup-"]');
        if (!blocks.length) {
            blocks = root.querySelectorAll('div');
        }
        for (var i = 0; i < blocks.length; i++) {
            var b = blocks[i];
            var head = b.querySelector('[class*="name-"]') || b.querySelector('.name');
            var wrap = b.querySelector('[class*="wrapper-"]');
            if (!head || !wrap) continue;
            var specs = wrap.querySelectorAll('[class*="spec-"]');
            if (!specs.length) specs = wrap.children;
            var opts = [];
            for (var j = 0; j < specs.length; j++) {
                var cls = specs[j].className || '';
                opts.push({
                    idx: j,
                    text: textOf(specs[j]),
                    active: cls.indexOf('active') >= 0,
                    disabled: cls.indexOf('disabled') >= 0 || cls.indexOf('soldOut') >= 0
                });
            }
            if (opts.length) {
                groups.push({ gi: groups.length, label: textOf(head), options: opts, _el: b });
            }
        }
        return groups;
    }

    function groupElements() {
        var root = document.querySelector('.package-wrapper') || document;
        var out = [];
        var blocks = root.querySelectorAll('[class*="skuGroup-"]');
        for (var i = 0; i < blocks.length; i++) {
            var head = blocks[i].querySelector('[class*="name-"]') || blocks[i].querySelector('.name');
            var wrap = blocks[i].querySelector('[class*="wrapper-"]');
            if (head && wrap) out.push(blocks[i]);
        }
        return out;
    }

    function specsOf(block) {
        var wrap = block.querySelector('[class*="wrapper-"]');
        if (!wrap) return [];
        var s = wrap.querySelectorAll('[class*="spec-"]');
        return s.length ? Array.prototype.slice.call(s) : Array.prototype.slice.call(wrap.children);
    }

    function stepper() {
        var body = document.querySelector('.quantityBody') || document.querySelector('.unit-list');
        if (!body) return null;
        var box = body.querySelector('[class*="counter-"]');
        if (!box) return null;
        var plus = box.querySelector('.klk-icon-icon_other_plus_xs');
        var minus = box.querySelector('.klk-icon-icon_other_minus_xs');
        var valueEl = box.querySelector('[class*="value-"]');
        function btnOf(icon) {
            if (!icon) return null;
            var el = icon;
            while (el && el !== box && !(el.className || '').match(/btn-/)) el = el.parentElement;
            return el && el !== box ? el : (icon.parentElement || null);
        }
        function disabled(btn) {
            return !btn || (btn.className || '').indexOf('Disabled') >= 0;
        }
        var raw = valueEl ? (valueEl.textContent || '').trim() : '';
        var current = /^\d+$/.test(raw) ? parseInt(raw, 10) : null;
        return { box: box, plusBtn: btnOf(plus), minusBtn: btnOf(minus),
                 current: current, disabledPlus: disabled(btnOf(plus)) };
    }

    function findButton(texts) {
        var buttons = document.querySelectorAll('button');
        for (var i = 0; i < buttons.length; i++) {
            var b = buttons[i];
            var t = (b.textContent || '').replace(/\s+/g, '');
            if (!t) continue;
            for (var j = 0; j < texts.length; j++) {
                if (t.indexOf(texts[j]) >= 0) {
                    var cls = b.className || '';
                    return { el: b, text: t.slice(0, 12),
                             enabled: !b.disabled && cls.indexOf('klk-button-disabled') < 0 };
                }
            }
        }
        return null;
    }

    // The seat-assignment modal, located and read but never acted on here.
    //
    // Verified against the saved 電腦選位 page: the container carries
    // seatModal_main-*, the header's right slot holds the hold countdown as mm:ss, and the
    // two buttons are 自行選位 (outlined) and 確認 (primary). Only that one page had the
    // modal, so the hash is not proven stable the way skuGroup- is - hence the text-based
    // fallback, which insists the dialog actually mentions seats. Without that condition any
    // confirm box on the page (cookies, login, a generic prompt) would qualify.
    function seatDialog() {
        var box = null;
        var byClass = document.querySelector('[class*="seatModal_main-"]') ||
                      document.querySelector('[class*="seatModal-"]');
        if (byClass && byClass.offsetParent !== null) {
            box = byClass;
        } else {
            var modals = document.querySelectorAll('.klk-modal, [class*="modal"]');
            for (var i = 0; i < modals.length; i++) {
                var m = modals[i];
                if (m.offsetParent === null) continue;
                var body = (m.textContent || '');
                if (body.indexOf('\u6642\u9593\u5230\u4e86') >= 0) continue;   // timeout dialog
                if (body.indexOf('\u5ea7\u4f4d') < 0 && body.indexOf('\u9078\u4f4d') < 0) continue;
                box = m;
                break;
            }
        }
        if (!box) return null;

        var btn = null;
        var btns = box.querySelectorAll('button');
        for (var j = 0; j < btns.length; j++) {
            var b = btns[j];
            var t = (b.textContent || '').replace(/\s+/g, '');
            if (t.indexOf('\u78ba\u8a8d') < 0 && t.indexOf('\u78ba\u5b9a') < 0) continue;
            if (t.indexOf('\u81ea\u884c\u9078\u4f4d') >= 0) continue;          // "pick my own seats"
            if (b.disabled || (b.className || '').indexOf('klk-button-disabled') >= 0) continue;
            btn = b;
            break;
        }
        if (!btn) return null;

        // How long Klook says the hold has left. Read from the header slot that holds
        // nothing else; failing that, from the one element inside the modal whose entire
        // text is mm:ss - matching loosely would pick up the showtime ("下午6:00") instead.
        var remain = null;
        var clock = box.querySelector('[class*="pc_header_right"]');
        var raw = clock ? (clock.textContent || '').trim() : '';
        if (!/^\d{1,2}:\d{2}$/.test(raw)) {
            raw = '';
            var all = box.querySelectorAll('*');
            for (var k = 0; k < all.length; k++) {
                var s = (all[k].textContent || '').trim();
                if (/^\d{1,2}:\d{2}$/.test(s)) raw = s;
            }
        }
        if (raw) {
            var mm = raw.split(':');
            remain = parseInt(mm[0], 10) * 60 + parseInt(mm[1], 10);
        }

        // The modal opens with a paragraph of zoom instructions; the part worth putting in
        // a notification starts at the seat summary.
        var full = (box.textContent || '').replace(/\s+/g, ' ');
        var at = full.indexOf('已選');
        if (at >= 0) full = full.slice(at);
        return { btn: btn, remain: remain, seats: full.slice(0, 160) };
    }
'''


async def _eval(tab, body, timeout=5.0, await_promise=False):
    """Run a JS snippet with the shared helpers in scope; returns the parsed object."""
    script = "(function(){" + CONST_KLOOK_JS_HELPERS + "\n" + body + "\n})();"
    try:
        raw = await asyncio.wait_for(
            tab.evaluate(script, await_promise=await_promise), timeout=timeout)
    except Exception as exc:
        return {"error": str(exc)[:120]}
    parsed = util.parse_nodriver_result(raw)
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except Exception:
            return {"error": "unparsable result"}
    return parsed if isinstance(parsed, dict) else {"error": "unexpected result"}


async def nodriver_klook_read_state(tab):
    """Snapshot of the booking widget: which groups exist, what is selected, quantity."""
    return await _eval(tab, r'''
        var groups = readGroups().map(function (g) {
            return { label: g.label, options: g.options.map(function (o) {
                return { text: o.text, active: o.active, disabled: o.disabled };
            }) };
        });
        var st = stepper();
        var next = findButton(['\u4e0b\u4e00\u6b65', 'Next']);
        return JSON.stringify({
            groups: groups,
            hasWidget: groups.length > 0,
            quantity: st ? st.current : null,
            plusDisabled: st ? st.disabledPlus : null,
            nextFound: !!next,
            nextEnabled: next ? next.enabled : false,
            url: location.href
        });
    ''')


async def nodriver_klook_dismiss_timeout(tab, debug):
    """Close the "sorry, time is up" dialog. Returns True when one was there.

    Its appearance means the held slot is gone, so the caller should treat it as a reset
    rather than carrying on with whatever it was doing.
    """
    result = await _eval(tab, r'''
        var texts = ['\u6642\u9593\u5230\u4e86', '\u91cd\u65b0\u6392\u968a', '\u62b1\u6b49'];
        var modals = document.querySelectorAll('.klk-modal, [class*="modal"]');
        for (var i = 0; i < modals.length; i++) {
            var m = modals[i];
            if (m.offsetParent === null) continue;
            var body = (m.textContent || '');
            var hit = false;
            for (var j = 0; j < texts.length; j++) { if (body.indexOf(texts[j]) >= 0) hit = true; }
            if (!hit) continue;
            var btns = m.querySelectorAll('button');
            for (var k = 0; k < btns.length; k++) {
                var t = (btns[k].textContent || '').replace(/\s+/g, '');
                if (t.indexOf('OK') >= 0 || t.indexOf('\u78ba\u5b9a') >= 0 || t.indexOf('\u6211\u77e5\u9053\u4e86') >= 0) {
                    btns[k].click();
                    return JSON.stringify({ found: true, clicked: true, text: body.slice(0, 60) });
                }
            }
            return JSON.stringify({ found: true, clicked: false, text: body.slice(0, 60) });
        }
        return JSON.stringify({ found: false });
    ''')
    if result.get("found"):
        debug.log(f"[KLOOK] Timeout dialog: {result.get('text', '')}")
        if result.get("clicked"):
            debug.log("[KLOOK] Dismissed; the held slot is gone, starting over")
        return True
    return False


async def nodriver_klook_select_options(tab, config_dict, debug):
    """Pick one option per group using the priority list from the area keyword box.

    Terms are matched against every group's options at once rather than group by group.
    A BIGBANG package option is identified by a package name AND a seat tier, and there is
    no way to know in advance whether Klook renders those as one group or two - matching
    across all of them makes the same keyword work either way.
    """
    groups = _keyword_groups(config_dict)
    excludes = _exclude_terms(config_dict)
    fallback = bool(config_dict.get("area_auto_fallback", False))

    payload = {
        "priorities": [g.split() for g in groups],
        "excludes": excludes,
        "allowFallback": fallback,
    }
    result = await _eval(tab, '''
        var cfg = ''' + json.dumps(payload, ensure_ascii=True) + r''';
        var blocks = groupElements();
        if (!blocks.length) return JSON.stringify({ ok: false, reason: 'no-groups' });

        function excluded(text) {
            for (var i = 0; i < cfg.excludes.length; i++) {
                if (cfg.excludes[i] && text.indexOf(norm(cfg.excludes[i])) >= 0) return true;
            }
            return false;
        }

        // A priority is a set of terms that must ALL be satisfied. Terms may describe one
        // option ("B區 5280" is a single spec) or span groups ("套票 1" plus
        // "VIP 1" when the event adds a package group). Assigning greedily term by term got
        // the first case wrong: matching "B區" marked the whole group used, so "5280"
        // could never land on the same option.
        //
        // Instead each group takes the option covering the MOST outstanding terms, and those
        // terms are struck off. Both shapes fall out of that, and a term that no option can
        // cover fails the priority, as it should.
        function selectable(el) {
            var cls = el.className || '';
            if (cls.indexOf('disabled') >= 0 || cls.indexOf('soldOut') >= 0) return false;
            return !excluded(textOf(el));
        }

        function planFor(terms) {
            var remaining = [];
            for (var t = 0; t < terms.length; t++) {
                var term = norm(terms[t]);
                if (term) remaining.push(term);
            }
            if (!remaining.length) return null;

            var plan = [];
            var used = {};
            while (remaining.length) {
                var best = null;
                for (var b = 0; b < blocks.length; b++) {
                    if (used[b]) continue;
                    var specs = specsOf(blocks[b]);
                    for (var s = 0; s < specs.length; s++) {
                        if (!selectable(specs[s])) continue;
                        var txt = textOf(specs[s]);
                        var covered = [];
                        for (var r = 0; r < remaining.length; r++) {
                            if (txt.indexOf(remaining[r]) >= 0) covered.push(remaining[r]);
                        }
                        if (covered.length && (!best || covered.length > best.covered.length)) {
                            best = { b: b, s: s, text: txt, covered: covered };
                        }
                    }
                }
                if (!best) return null;          // a term no option can satisfy
                used[best.b] = true;
                plan.push(best);
                remaining = remaining.filter(function (r) { return best.covered.indexOf(r) < 0; });
            }
            return plan.length ? plan : null;
        }

        var chosen = null, matchedIndex = -1;
        for (var p = 0; p < cfg.priorities.length && !chosen; p++) {
            var plan = planFor(cfg.priorities[p]);
            if (plan) { chosen = plan; matchedIndex = p; }
        }

        if (!chosen) {
            if (!cfg.allowFallback) {
                var avail = [];
                for (var b = 0; b < blocks.length; b++) {
                    specsOf(blocks[b]).forEach(function (el) {
                        var c = el.className || '';
                        if (c.indexOf('disabled') < 0 && c.indexOf('soldOut') < 0) avail.push(textOf(el));
                    });
                }
                return JSON.stringify({ ok: false, reason: 'no-keyword-match',
                                        available: avail.slice(0, 20) });
            }
            // Fallback: take the first selectable option in each group.
            chosen = [];
            for (var b2 = 0; b2 < blocks.length; b2++) {
                var sp = specsOf(blocks[b2]);
                for (var s2 = 0; s2 < sp.length; s2++) {
                    var c2 = sp[s2].className || '';
                    if (c2.indexOf('disabled') >= 0 || c2.indexOf('soldOut') >= 0) continue;
                    if (excluded(textOf(sp[s2]))) continue;
                    chosen.push({ b: b2, s: s2, text: textOf(sp[s2]) });
                    break;
                }
            }
        }

        var clicked = [];
        for (var i = 0; i < chosen.length; i++) {
            var specs = specsOf(blocks[chosen[i].b]);
            var el = specs[chosen[i].s];
            if (!el) continue;
            // Clicking an already-active option can toggle it off on some widgets.
            if ((el.className || '').indexOf('active') < 0) el.click();
            clicked.push(chosen[i].text);
        }

        // Every group has to end up with something selected. Klook keeps the quantity step
        // locked until they all are, so a keyword that pins down the ticket type but says
        // nothing about, say, the package group leaves the run stuck on a greyed-out
        // "next" with no explanation. Re-read the groups first: clicking one can re-render
        // the others.
        var after = groupElements();
        var autofilled = [];
        var unfilled = [];
        for (var g = 0; g < after.length; g++) {
            var sp = specsOf(after[g]);
            var live = false;
            for (var q = 0; q < sp.length; q++) {
                if ((sp[q].className || '').indexOf('active') >= 0) live = true;
            }
            if (live) continue;
            var headEl = after[g].querySelector('[class*="name-"]') || after[g].querySelector('.name');
            var label = headEl ? textOf(headEl) : ('#' + g);
            if (!cfg.allowFallback) { unfilled.push(label); continue; }
            var filled = false;
            for (var q2 = 0; q2 < sp.length; q2++) {
                var c3 = sp[q2].className || '';
                if (c3.indexOf('disabled') >= 0 || c3.indexOf('soldOut') >= 0) continue;
                if (excluded(textOf(sp[q2]))) continue;
                sp[q2].click();
                autofilled.push(label + '=' + textOf(sp[q2]));
                filled = true;
                break;
            }
            if (!filled) unfilled.push(label);
        }

        return JSON.stringify({ ok: unfilled.length === 0, reason: unfilled.length ? 'incomplete' : '',
                                matchedPriority: matchedIndex, clicked: clicked,
                                autofilled: autofilled, unfilled: unfilled });
    ''')

    if result.get("ok"):
        idx = result.get("matchedPriority", -1)
        which = f"priority #{idx + 1}" if idx >= 0 else "fallback (no keyword matched)"
        debug.log(f"[KLOOK] Selected via {which}: {result.get('clicked')}")
        auto = result.get("autofilled") or []
        if auto:
            # Worth shouting about: these were picked by the program, not by the keyword.
            debug.log(f"[KLOOK] Groups the keyword did not cover, filled by fallback: {auto}")
            print("[KLOOK] \u4e0b\u5217\u9078\u9805\u4e0d\u662f\u95dc\u9375\u5b57\u9078\u7684\uff0c"
                  "\u662f\u905e\u88dc\u81ea\u52d5\u6311\u7684\uff1a" + str(auto))
        return True

    reason = result.get("reason") or result.get("error")
    if reason == "incomplete":
        debug.log(f"[KLOOK] These groups still have nothing selected: {result.get('unfilled')}. "
                  "The next button stays disabled until every group is set.")
        print("[KLOOK] \u9019\u5e7e\u7d44\u9078\u9805\u9084\u6c92\u9078\u5230\uff1a"
              + str(result.get("unfilled"))
              + "\u3002\u95dc\u9375\u5b57\u5fc5\u9808\u6bcf\u4e00\u7d44\u90fd\u8986\u84cb\u5230\uff0c"
                "\u5426\u5247\u300c\u4e0b\u4e00\u6b65\u300d\u6703\u4e00\u76f4\u662f\u7070\u7684\u3002")
    elif reason == "no-keyword-match":
        debug.log("[KLOOK] No option matched the area keyword; still refreshing. "
                  f"Selectable right now: {result.get('available')}")
    else:
        debug.log(f"[KLOOK] Option selection failed: {reason}")
    return False


async def nodriver_klook_set_quantity(tab, config_dict, debug):
    """Drive the stepper to ticket_number. Idempotent: re-entry does not stack tickets."""
    want = int(config_dict.get("ticket_number", 1) or 1)
    allow_less = bool(config_dict.get("advanced", {}).get("allow_less_tickets", False))

    result = await _eval(tab, '''
        var want = ''' + str(want) + r''';
        var allowLess = ''' + ("true" if allow_less else "false") + r''';
        var st = stepper();
        if (!st) return JSON.stringify({ ok: false, reason: 'no-stepper' });
        if (st.current === null) return JSON.stringify({ ok: false, reason: 'unreadable' });

        // Read the current value and move by the difference, rather than clicking `want`
        // times. The main loop re-enters this handler every cycle, so blind clicking would
        // stack extra tickets on any pass where the submit did not go through.
        var before = st.current;
        var delta = want - before;
        var clicks = 0;
        var budget = Math.min(Math.abs(delta), 20);
        if (delta > 0) {
            for (var i = 0; i < budget; i++) {
                if (st.plusBtn && (st.plusBtn.className || '').indexOf('Disabled') >= 0) break;
                st.plusBtn.click(); clicks++;
                st = stepper();
                if (!st) break;
            }
        } else if (delta < 0 && st.minusBtn) {
            for (var j = 0; j < budget; j++) { st.minusBtn.click(); clicks++; st = stepper(); if (!st) break; }
        }

        var after = stepper();
        var got = after ? after.current : null;
        if (!allowLess && got !== null && got < want) {
            // The stepper caps at whatever stock is left. A short order on a limited
            // presale usually cannot be topped up later, so undo and let the loop retry.
            var undo = stepper();
            for (var k = 0; k < 20 && undo && undo.current > 0 && undo.minusBtn; k++) {
                undo.minusBtn.click(); undo = stepper();
            }
            return JSON.stringify({ ok: false, reason: 'insufficient', before: before,
                                    got: got, want: want });
        }
        return JSON.stringify({ ok: true, before: before, after: got, clicks: clicks });
    ''')

    if result.get("ok"):
        debug.log(f"[KLOOK] Quantity {result.get('before')} -> {result.get('after')} "
                  f"({result.get('clicks')} clicks)")
        return True
    reason = result.get("reason") or result.get("error")
    if reason == "insufficient":
        debug.log(f"[KLOOK] Only {result.get('got')} available, wanted {result.get('want')}; "
                  "selection undone. Turn on allow_less_tickets to accept short orders.")
    else:
        debug.log(f"[KLOOK] Quantity step failed: {reason}")
    return False


async def nodriver_klook_press_next(tab, debug):
    """Press the widget's next button, once the site says it is enabled."""
    now = time.time()
    if now - _state.get("last_press_at", 0) < CONST_KLOOK_PRESS_GUARD_SEC:
        return False
    result = await _eval(tab, r'''
        var next = findButton(['\u4e0b\u4e00\u6b65', 'Next']);
        if (!next) return JSON.stringify({ ok: false, reason: 'not-found' });
        if (!next.enabled) return JSON.stringify({ ok: false, reason: 'disabled' });
        next.el.click();
        return JSON.stringify({ ok: true, text: next.text });
    ''')
    if result.get("ok"):
        _state["last_press_at"] = now
        debug.log(f"[KLOOK] Pressed '{result.get('text')}'")
        return True
    if result.get("reason") == "disabled":
        debug.log("[KLOOK] Next button still disabled (selection incomplete)")
    return False


def _reset_seat_wait():
    """Forget the countdown. Called whenever the seat dialog is not on screen."""
    _state["seat_seen_at"] = 0
    _state["seat_wait_sec"] = 0.0
    _state["seat_notice_at"] = 0
    _state["seat_announced"] = False


def _accumulate_seat_wait(now):
    """Seconds the seat dialog has been up *while the bot was running*, added per cycle.

    Counted this way rather than from first sight, so time spent paused does not burn the
    countdown - whoever steps away comes back to the countdown they left. A gap longer than
    CONST_KLOOK_SEAT_CYCLE_CAP_SEC means the bot was not looping (paused, or the tab was
    somewhere else) and counts as nothing: crediting even part of it would let a long pause
    swallow the rest of the window and confirm the moment the user resumes.
    """
    last = _state.get("seat_seen_at") or 0
    gap = (now - last) if last else 0.0
    if gap < 0 or gap > CONST_KLOOK_SEAT_CYCLE_CAP_SEC:
        gap = 0.0
    total = _state.get("seat_wait_sec", 0.0) + gap
    _state["seat_wait_sec"] = total
    _state["seat_seen_at"] = now
    return total


async def nodriver_klook_read_seat_dialog(tab):
    """Is the seat modal up, and how long does Klook say the hold has left? Looks only."""
    return await _eval(tab, r'''
        var d = seatDialog();
        return JSON.stringify(d ? { found: true, seats: d.seats, remain: d.remain }
                                : { found: false });
    ''')


async def nodriver_klook_confirm_seats(tab, config_dict, debug):
    """Decide what to do about the assigned seats. Returns 'absent', 'waiting' or 'confirmed'.

    The seats are held on a countdown Klook prints in the modal header. Confirming the
    instant the modal opens spends that whole window on the bot's behalf, when the person
    watching may want to see what they got and decide - so the dialog is left alone for
    CONST_KLOOK_SEAT_CONFIRM_DELAY_SEC of running time first.

    That wait never costs the seats: whenever the on-screen countdown drops to
    CONST_KLOOK_SEAT_SAFETY_SEC the button is pressed regardless of how long the bot has
    been waiting. So the 45 seconds are a decision window when the hold is generous and
    quietly shrink when it is not, instead of being a fixed bet on how long Klook waits.

    Pausing suppresses all of this: the main loop stops dispatching here, so a paused bot
    never confirms a seat. That is the point of pausing on this screen.
    """
    dialog = await nodriver_klook_read_seat_dialog(tab)
    if not dialog.get("found"):
        if _state.get("seat_seen_at") and not _state.get("seats_confirmed"):
            debug.log("[KLOOK] Seat dialog closed; countdown reset")
        _reset_seat_wait()
        return "absent"

    now = time.time()
    waited = _accumulate_seat_wait(now)
    remain = dialog.get("remain")
    countdown = f"{int(remain)}s left on the hold" if isinstance(remain, int) else "hold timer unreadable"

    if not _state.get("seat_announced"):
        _state["seat_announced"] = True
        seats = dialog.get("seats", "")
        debug.log(f"[KLOOK] Seats assigned ({countdown}): {seats}")
        print(f"[KLOOK] \u5df2\u5206\u914d\u5ea7\u4f4d\uff1a{seats}")
        print(f"[KLOOK] {int(CONST_KLOOK_SEAT_CONFIRM_DELAY_SEC)} "
              "\u79d2\u5167\u6c92\u6709\u52d5\u4f5c\u7684\u8a71\uff0c\u7a0b\u5f0f\u6703\u81ea\u52d5\u6309"
              "\u300c\u78ba\u8a8d\u300d\u9032\u5165\u586b\u8cc7\u6599\u9801\uff1b"
              "\u60f3\u81ea\u5df1\u6c7a\u5b9a\u8acb\u5148\u6309\u66ab\u505c\u3002")
        if config_dict.get("advanced", {}).get("play_sound", {}).get("ticket"):
            play_sound_while_ordering(config_dict)
        send_discord_notification(config_dict, "ticket", "Klook")
        send_telegram_notification(config_dict, "ticket", "Klook")

    deadline_reached = waited >= CONST_KLOOK_SEAT_CONFIRM_DELAY_SEC
    hold_expiring = isinstance(remain, int) and remain <= CONST_KLOOK_SEAT_SAFETY_SEC
    if not deadline_reached and not hold_expiring:
        if now - (_state.get("seat_notice_at") or 0) >= 10:
            _state["seat_notice_at"] = now
            left = CONST_KLOOK_SEAT_CONFIRM_DELAY_SEC - waited
            debug.log(f"[KLOOK] Seat dialog open, {left:.0f}s before auto-confirm ({countdown})")
            print(f"[KLOOK] \u5ea7\u4f4d\u5c1a\u672a\u78ba\u8a8d\uff0c{int(left)} "
                  "\u79d2\u5f8c\u81ea\u52d5\u6309\u78ba\u8a8d\u3002")
        return "waiting"

    # A click that did not take should be retried, but not hammered.
    if now - (_state.get("seat_click_at") or 0) < CONST_KLOOK_PRESS_GUARD_SEC:
        return "waiting"
    _state["seat_click_at"] = now

    if hold_expiring and not deadline_reached:
        debug.log(f"[KLOOK] Hold almost gone ({countdown}); confirming early")
        print("[KLOOK] \u4fdd\u7559\u6642\u9593\u5feb\u5230\u4e86\uff0c\u63d0\u524d\u6309\u4e0b\u78ba\u8a8d\u3002")

    result = await _eval(tab, r'''
        var d = seatDialog();
        if (!d) return JSON.stringify({ ok: false });
        d.btn.click();
        return JSON.stringify({ ok: true, seats: d.seats });
    ''')
    if result.get("ok"):
        debug.log(f"[KLOOK] Confirmed after {waited:.0f}s of waiting: {result.get('seats')}")
        print("[KLOOK] \u5df2\u6309\u4e0b\u78ba\u8a8d\uff0c\u9032\u5165\u586b\u5beb\u8cc7\u8a0a\u9801\u9762\u3002")
        return "confirmed"
    return "waiting"


async def nodriver_klook_paused_main(tab, url, config_dict):
    """What the bot does on a Klook page while paused: look, and say so. Never click.

    Paused means the person is driving, so nothing here presses anything. It exists only
    because silence would be dangerous on the seat screen - the hold expires in about a
    minute, and someone who paused earlier needs to be told that no one is going to press
    the confirm button for them.
    """
    try:
        if 'klook.com' not in (url or ''):
            return
        dialog = await nodriver_klook_read_seat_dialog(tab)
        if not dialog.get("found"):
            _state["paused_seat_notice"] = False
            return
        # Keep the auto-confirm countdown still: paused seconds are not "no action from
        # the user", they are the user holding the bot off.
        _state["seat_seen_at"] = time.time()
        if _state.get("paused_seat_notice"):
            return
        _state["paused_seat_notice"] = True
        debug = util.create_debug_logger(config_dict)
        debug.log("[KLOOK] Seat dialog is open while paused; not confirming")
        print("[KLOOK] \u76ee\u524d\u662f\u66ab\u505c\u72c0\u614b\uff0c\u9078\u4f4d\u756b\u9762\u7684"
              "\u300c\u78ba\u5b9a\u300d\u4e0d\u6703\u81ea\u52d5\u6309\u3002"
              "\u5ea7\u4f4d\u53ea\u4fdd\u7559\u7d04\u4e00\u5206\u9418\uff0c"
              "\u8acb\u81ea\u884c\u6309\u4e0b\u78ba\u5b9a\uff0c\u6216\u5148\u89e3\u9664\u66ab\u505c\u3002")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"[KLOOK ERROR] Paused check failed: {type(exc).__name__}: {exc}")


async def _nodriver_klook_main_impl(tab, url, config_dict, ocr, Captcha_Browser):
    debug = util.create_debug_logger(config_dict)

    if not _state:
        _state["seats_confirmed"] = False
        _state["handed_over"] = False
        _state["last_press_at"] = 0
        _state["widget_wait_started"] = 0
        _state["seat_click_at"] = 0
        _state["paused_seat_notice"] = False
        _reset_seat_wait()

    if await check_and_handle_pause(config_dict):
        return _get_status()

    # Running again: let the paused-state reminder fire afresh next time it is needed.
    _state["paused_seat_notice"] = False

    low = url.lower()

    # Past the seat dialog the user takes over: the details form and payment are not
    # time-critical and are not automated here. Say so once, then stay out of the way.
    if any(k in low for k in ('/booking', '/checkout', '/payment', '/order/')):
        if not _state.get("handed_over"):
            _state["handed_over"] = True
            debug.log("[KLOOK] Reached the details/payment step - stopping here.")
            print("[KLOOK] \u5df2\u62b5\u9054\u586b\u8cc7\u6599\u9801\u9762\uff0c\u7a0b\u5f0f\u5230\u6b64\u70ba\u6b62\uff0c"
                  "\u8acb\u81ea\u884c\u5b8c\u6210\u5be6\u540d\u5236\u8cc7\u6599\u8207\u4ed8\u6b3e\u3002")
            if config_dict.get("advanced", {}).get("play_sound", {}).get("order"):
                play_sound_while_ordering(config_dict)
            send_discord_notification(config_dict, "order", "Klook")
            send_telegram_notification(config_dict, "order", "Klook")
        return _get_status()

    # A timeout dialog means the held slot expired; clear it and start the cycle over.
    if await nodriver_klook_dismiss_timeout(tab, debug):
        _state["last_press_at"] = 0
        return _get_status()

    # Seats already assigned? That dialog is the urgent one, so it is checked before
    # anything else on the page. It is not pressed straight away - see the function for the
    # countdown that leaves the decision to the user first.
    seat_state = await nodriver_klook_confirm_seats(tab, config_dict, debug)
    if seat_state != "absent":
        # Whether it confirmed or is still giving the user their window, the modal owns the
        # page now. Falling through would re-pick options and re-press "next" underneath an
        # open seat dialog, on seats that are already held.
        if seat_state == "confirmed":
            _state["seats_confirmed"] = True
        return _get_status()

    state = await nodriver_klook_read_state(tab)
    if state.get("error"):
        debug.log(f"[KLOOK] Could not read the page: {state['error']}")
        return _get_status()

    if not state.get("hasWidget"):
        # Before the on-sale moment the wrapper exists but holds no options yet.
        started = _state.get("widget_wait_started") or time.time()
        _state["widget_wait_started"] = started
        waited = time.time() - started
        if waited < CONST_KLOOK_WIDGET_WAIT_SEC:
            return _get_status()
        debug.log(f"[KLOOK] Booking options still not rendered after {waited:.0f}s "
                  "(not on sale yet, or the page needs a refresh)")
        _state["widget_wait_started"] = time.time()
        return _get_status()

    _state["widget_wait_started"] = 0
    if debug.enabled:
        for group in state.get("groups", []):
            picked = [o["text"] for o in group.get("options", []) if o.get("active")]
            debug.log(f"[KLOOK] Group '{group.get('label')}': "
                      f"{len(group.get('options', []))} option(s), selected={picked}")

    if not await nodriver_klook_select_options(tab, config_dict, debug):
        return _get_status()

    if not await nodriver_klook_set_quantity(tab, config_dict, debug):
        return _get_status()

    await nodriver_klook_press_next(tab, debug)
    return _get_status()


async def nodriver_klook_main(tab, url, config_dict, ocr, Captcha_Browser):
    """Klook entry point.

    Guarded the same way as the other platforms: the main loop has no try/except between
    here and asyncio.run, so an exception escaping would take the whole process down
    mid-purchase. One lost cycle is recoverable; a dead process is not.
    """
    try:
        return await _nodriver_klook_main_impl(tab, url, config_dict, ocr, Captcha_Browser)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        debug = util.create_debug_logger(config_dict)
        print(f"[KLOOK ERROR] Cycle aborted: {type(exc).__name__}: {exc}")
        debug.log(f"[KLOOK ERROR] {traceback.format_exc()}")
        return _get_status()
