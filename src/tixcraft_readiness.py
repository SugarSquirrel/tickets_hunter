"""Document readiness for the TixCraft/Indievox date and ticket paths only.

No requests, clicks, settings or submission decisions are made here. Once a
navigation command is issued, fallback waits on that command; it never retries it.
"""

import asyncio
import json
import time
from urllib.parse import urldefrag, urljoin, urlsplit

from flow_timing import flow_stage, log_navigation_timing


DOCUMENT_SNAPSHOT_JS = """
(() => {
    let nav = null;
    let navigationTiming = {};
    try {
        nav = performance.getEntriesByType('navigation')[0];
    } catch (_) {}
    try {
        if (nav) {
            for (const key of ['startTime', 'requestStart', 'responseStart', 'responseEnd',
                               'domContentLoadedEventEnd', 'redirectStart', 'redirectEnd', 'redirectCount']) {
                const value = nav[key];
                if (typeof value === 'number' && Number.isFinite(value) && value >= 0) {
                    navigationTiming[key] = value;
                }
            }
        }
    } catch (_) {
        // Optional telemetry must not prevent the existing readiness snapshot.
        navigationTiming = {};
    }
    const select = document.querySelector('.mobile-select, select[id*="TicketForm_ticketPrice_"]');
    return JSON.stringify({
        href: location.href,
        document_id: performance.timeOrigin,
        navigation_timing: navigationTiming,
        dom_ready: document.readyState === 'complete' || !!(nav && nav.domContentLoadedEventEnd > 0),
        area: !!document.querySelector('.zone a'),
        ticket: !!(select && select.closest('form') && document.getElementById('TicketForm_agree')),
        verify: !!(document.querySelector('.zone-verify') && document.querySelector("input[name='checkCode']")),
        select: !!select
    });
})()
"""


def supported_url(url):
    """Reject lookalike hosts, userinfo and non-web schemes."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or '').lower()
        return (parts.scheme in ('http', 'https') and not parts.username
                and not parts.password and parts.port in (None, 80, 443)
                and any(host == domain or host.endswith('.' + domain)
                        for domain in ('tixcraft.com', 'indievox.com')))
    except (TypeError, ValueError):
        return False


def document_route(url):
    if not supported_url(url):
        return None
    path = urlsplit(url).path
    for route, prefix in (('area', '/ticket/area'), ('ticket', '/ticket/ticket'),
                          ('verify', '/ticket/verify'), ('login', '/login')):
        if path == prefix or path.startswith(prefix + '/'):
            return route
    return None


async def read_document(tab):
    """Read the actual document, never the eventually updated target URL."""
    try:
        value = await asyncio.wait_for(tab.evaluate(DOCUMENT_SNAPSHOT_JS), timeout=0.5)
        if isinstance(value, str):
            value = json.loads(value)
        if (isinstance(value, dict) and isinstance(value.get('href'), str)
                and isinstance(value.get('document_id'), (int, float))):
            return value
    except Exception:
        # Execution contexts briefly disappear on redirect. Callers decide
        # whether to poll again or use the legacy waiting behavior.
        pass
    return None


def ticket_document_matches(snapshot, expected_url, expected_document=None):
    # Keep unsupported platforms and unavailable CDP snapshots on their old path.
    if not supported_url(expected_url) or snapshot is None:
        return True
    return (document_route(snapshot['href']) == 'ticket'
            and urldefrag(snapshot['href'])[0] == urldefrag(expected_url)[0]
            and (expected_document is None
                 or snapshot['document_id'] == expected_document['document_id']))


async def navigate_date(tab, data_href, source_url, config_dict, navigate_command,
                        timeout=2.0, poll_interval=0.025):
    """One Page.navigate, then new-document route/DOM readiness or legacy idle."""
    try:
        destination = urljoin(source_url, data_href)
        source_path = urlsplit(source_url).path
    except (TypeError, ValueError):
        await tab.get(data_href)
        return 'legacy_route'
    if (not supported_url(source_url) or not source_path.startswith('/activity/game/')
            or document_route(destination) is None):
        await tab.get(data_href)
        return 'legacy_route'

    before = await read_document(tab)
    if (before is None or not supported_url(before['href'])
            or not callable(getattr(tab, 'send', None))
            or not callable(getattr(tab, 'wait', None))
            or not callable(getattr(tab, 'update_target', None))):
        await tab.get(data_href)
        return 'legacy_preflight'

    fallback = 'timeout'
    try:
        with flow_stage(config_dict, 'date_navigate_send'):
            result = await tab.send(navigate_command(destination))
        # Installed zendriver 0.15.3 returns (frameId, loaderId, errorText).
        if isinstance(result, tuple) and len(result) > 2 and result[2]:
            fallback = 'navigate_error'
        else:
            deadline = time.monotonic() + timeout
            with flow_stage(config_dict, 'date_route_ready') as timing:
                while True:
                    snapshot = await read_document(tab)
                    if snapshot is not None:
                        route = document_route(snapshot['href'])
                        if snapshot['document_id'] != before['document_id']:
                            if route is None:
                                fallback = 'unsupported_redirect'
                                break
                            if snapshot.get('dom_ready') and (route == 'login' or snapshot.get(route)):
                                # Tab.get's wait also refreshes this cache, used
                                # by the dispatch loop on the next iteration.
                                with flow_stage(config_dict, 'date_target_cache_update'):
                                    await tab.update_target()
                                log_navigation_timing(config_dict, snapshot)
                                timing.outcome = 'ready_' + route
                                return timing.outcome
                    if time.monotonic() >= deadline:
                        break
                    await asyncio.sleep(poll_interval)
                timing.outcome = fallback
    except Exception:
        fallback = 'navigate_error'

    # Identical final wait to Tab.get(), without sending a second navigation or
    # allowing the date caller to click its fallback links after a partial send.
    with flow_stage(config_dict, 'date_idle_fallback') as timing:
        timing.outcome = fallback
        try:
            await tab.wait()
        except Exception:
            timing.outcome = 'wait_error'
    return 'idle_' + fallback


async def wait_ticket_select(tab, expected_url, timeout=2.0, poll_interval=0.05):
    """Exit a stale selector wait promptly; keep the full timeout on same page."""
    before = await read_document(tab) if supported_url(expected_url) else None
    if before is None:
        await tab.wait_for('.mobile-select, select[id*="TicketForm_ticketPrice_"]', timeout=timeout)
        return True
    deadline = time.monotonic() + timeout
    snapshot = before
    while True:
        if snapshot is not None:
            if not ticket_document_matches(snapshot, expected_url, before):
                return False
            if snapshot.get('select'):
                return True
        if time.monotonic() >= deadline:
            return True  # Existing batch scan/sold-out/retry logic owns failure.
        await asyncio.sleep(poll_interval)
        snapshot = await read_document(tab)
