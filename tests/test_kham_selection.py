"""Offline KHAM date/area regressions using trimmed, sanitized repository fixtures."""

import copy
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from platforms import kham


class HtmlNode:
    def __init__(self, tag='', attrs=None):
        self.tag = tag
        self.attrs = dict(attrs or [])
        self.children = []

    def __str__(self):
        attrs = ''.join(f' {name}="{escape(value or "", quote=True)}"' for name, value in self.attrs.items())
        return f'<{self.tag}{attrs}>' + ''.join(str(child) for child in self.children) + f'</{self.tag}>'

    def get(self, name):
        return self.attrs.get(name)

    @property
    def string(self):
        return ''.join(str(child) for child in self.children)

    @string.setter
    def string(self, value):
        self.children = [escape(value)]

    def descendants(self):
        for child in self.children:
            if isinstance(child, HtmlNode):
                yield child
                yield from child.descendants()

    def select(self, selector):
        if selector in ('table.eventTABLE > tbody > tr', 'table#salesTable > tbody > tr.status_tr'):
            is_area = selector.startswith('table#')
            tables = [node for node in self.descendants() if node.tag == 'table' and
                      (node.get('id') == 'salesTable' if is_area else 'eventTABLE' in (node.get('class') or '').split())]
            return [row for table in tables for body in table.children
                    if isinstance(body, HtmlNode) and body.tag == 'tbody'
                    for row in body.children if isinstance(row, HtmlNode) and row.tag == 'tr'
                    and (not is_area or 'status_tr' in (row.get('class') or '').split())]
        if selector == 'table.eventTABLE button':
            return [button for table in self.descendants()
                    if table.tag == 'table' and 'eventTABLE' in (table.get('class') or '').split()
                    for button in table.descendants() if button.tag == 'button']
        if selector == 'button:not([disabled])':
            return [node for node in self.descendants() if node.tag == 'button' and 'disabled' not in node.attrs]
        raise AssertionError(f'Unexpected test selector: {selector}')

    def select_one(self, selector):
        matches = self.select(selector)
        return matches[0] if matches else None


class HtmlTree(HTMLParser):
    """Small DOM fixture reader; does not execute scripts or contact the site."""
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode('document')
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = HtmlNode(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(HtmlNode(tag, attrs))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(escape(data))


class Element:
    def __init__(self, node, tab):
        self.node = node
        self.tab = tab

    async def get_html(self):
        return str(self.node)

    async def query_selector(self, selector):
        node = self.node.select_one(selector)
        return Element(node, self.tab) if node else None

    async def click(self):
        self.tab.clicks.append(self.node.get('id') or self.node.get('onclick'))


class Tab:
    def __init__(self, html):
        self.soup = HtmlTree(html).root
        self.clicks = []
        self.reloads = 0
        self.selectors = []

    async def query_selector_all(self, selector):
        self.selectors.append(selector)
        return [Element(node, self) for node in self.soup.select(selector)]

    async def reload(self):
        self.reloads += 1


class KhamSelectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = {
            'ticket_number': 2,
            'keyword_exclude': '',
            'date_auto_select': {'mode': kham.CONST_FROM_TOP_TO_BOTTOM, 'date_keyword': '"2026/10/03"'},
            'area_auto_select': {'mode': kham.CONST_FROM_TOP_TO_BOTTOM, 'area_keyword': ''},
            'date_auto_fallback': False,
            'area_auto_fallback': False,
            'tixcraft': {'auto_reload_coming_soon_page': True},
            'advanced': {'auto_reload_page_interval': 1.75, 'verbose': False},
        }
        self.pause = AsyncMock(return_value=False)
        self.wait = AsyncMock(return_value=False)
        self.mark = unittest.mock.Mock()
        for target, replacement in (
            ('platforms.kham.check_and_handle_pause', self.pause),
            ('platforms.kham.asyncio_sleep_with_pause_check', self.wait),
            ('nodriver_common.mark_bot_reload', self.mark),
        ):
            context = patch(target, replacement)
            context.start()
            self.addCleanup(context.stop)

    def page(self, name):
        source = (ROOT / 'tests' / 'fixtures' / 'kham' / name).read_text(encoding='utf-8')
        # Restore selector evidence only in this non-executing HTML test double.
        return Tab(source.replace('data-original-onclick=', 'onclick='))

    async def select_date(self, tab):
        return await kham.nodriver_kham_date_auto_select(tab, 'kham.com.tw', self.config)

    async def select_area(self, tab):
        return await kham.nodriver_kham_performance(tab, self.config, None, 'kham.com.tw', '')

    async def test_saved_date_selects_regular_session(self):
        tab = self.page('2-date select.html')
        self.assertTrue(await self.select_date(tab))
        self.assertEqual(len(tab.clicks), 1)
        self.assertIn('P1D430L4', tab.clicks[0])
        self.assertEqual(tab.reloads, 0)

    async def test_date_accepts_plain_text_and_space_and_terms(self):
        tab = self.page('2-date select.html')
        self.config['date_auto_select']['date_keyword'] = '2026/11/21 17:00'
        self.assertTrue(await self.select_date(tab))
        self.assertIn('P1D4870B', tab.clicks[0])

    async def test_date_checks_all_priorities(self):
        tab = self.page('2-date select.html')
        self.config['date_auto_select']['date_keyword'] = '"missing","2026/11/21"'
        self.config['date_auto_fallback'] = True
        self.assertTrue(await self.select_date(tab))
        self.assertIn('P1D4870B', tab.clicks[0])

    async def test_date_semicolon_alternatives(self):
        tab = self.page('2-date select.html')
        self.config['date_auto_select']['date_keyword'] = 'missing;2026/11/21'
        self.assertTrue(await self.select_date(tab))
        self.assertIn('P1D4870B', tab.clicks[0])

    async def test_shared_date_exclusions_support_semicolon(self):
        tab = self.page('2-date select.html')
        self.config['date_auto_select']['date_keyword'] = ''
        self.config['keyword_exclude'] = '"2026/10/03;身障"'
        self.assertTrue(await self.select_date(tab))
        self.assertIn('P1D4870B', tab.clicks[0])

    async def test_completed_sessions_cannot_be_selected_again(self):
        tab = self.page('2-date select.html')
        self.config['_kham_completed_performances'] = ['p1d430l4']
        self.config['date_auto_select']['date_keyword'] = ''
        self.assertTrue(await self.select_date(tab))
        self.assertIn('P1D4870B', tab.clicks[0])

    async def test_unmatched_date_reloads_at_configured_interval(self):
        tab = self.page('2-date select.html')
        self.config['date_auto_select']['date_keyword'] = '"missing"'
        self.assertFalse(await self.select_date(tab))
        self.assertEqual(tab.clicks, [])
        self.assertEqual(tab.reloads, 1)
        self.wait.assert_awaited_once_with(1.75, self.config)
        self.mark.assert_called_once_with()

    async def test_empty_date_table_reloads(self):
        tab = Tab('<table class="eventTABLE"><tbody></tbody></table>')
        self.assertFalse(await self.select_date(tab))
        self.assertEqual(tab.reloads, 1)

    async def test_coming_soon_dates_reloads(self):
        tab = self.page('2-date select.html')
        for button in tab.soup.select('table.eventTABLE button'):
            button.string = '尚未開賣'
        self.assertFalse(await self.select_date(tab))
        self.assertEqual(tab.clicks, [])
        self.assertEqual(tab.reloads, 1)

    async def test_date_respects_disabled_reload_setting(self):
        tab = Tab('')
        self.config['tixcraft']['auto_reload_coming_soon_page'] = False
        self.assertFalse(await self.select_date(tab))
        self.assertEqual(tab.reloads, 0)

    async def test_area_handles_extra_classes_and_stock_100(self):
        tab = self.page('3-area select.html')
        self.config['area_auto_select']['area_keyword'] = '"2樓黃2E區3880元"'
        self.assertEqual(await self.select_area(tab), (True, False))
        self.assertEqual(tab.clicks, ['P1D9ZT7U'])

    async def test_area_stock_30_is_not_zero(self):
        tab = self.page('3-area select.html')
        self.config['area_auto_select']['area_keyword'] = '"2樓紅2C區3880元"'
        self.assertEqual(await self.select_area(tab), (True, False))
        self.assertEqual(tab.clicks, ['P1D9ZT7I'])

    async def test_area_rejects_insufficient_full_stock_count(self):
        tab = self.page('3-area select.html')
        self.config['ticket_number'] = 12
        self.config['area_auto_select']['area_keyword'] = '"2樓紅2C區3480元"'
        self.assertEqual(await self.select_area(tab), (False, False))
        self.assertEqual(tab.clicks, [])
        self.assertEqual(tab.reloads, 1)

    async def test_all_area_priorities_precede_fallback_click(self):
        tab = self.page('3-area select.html')
        self.config['area_auto_fallback'] = True
        self.config['area_auto_select']['area_keyword'] = '"missing","2樓黃2E區3880元"'
        before = copy.deepcopy(self.config)
        self.assertEqual(await self.select_area(tab), (True, False))
        self.assertEqual(tab.clicks, ['P1D9ZT7U'])
        self.assertEqual(self.config, before)
        self.assertEqual(tab.selectors, ['table#salesTable > tbody > tr.status_tr'])

    async def test_area_slot_semicolon_alternatives_and_space_terms(self):
        tab = self.page('3-area select.html')
        self.config['area_auto_select']['area_keyword'] = '"missing;2樓黃2E區 3,880"'
        self.assertEqual(await self.select_area(tab), (True, False))
        self.assertEqual(tab.clicks, ['P1D9ZT7U'])

    async def test_area_nested_and_group_preserves_comma_price(self):
        tab = self.page('3-area select.html')
        self.config['area_auto_select']['area_keyword'] = '["2樓黃2E區", "3,880"]'
        self.assertEqual(await self.select_area(tab), (True, False))
        self.assertEqual(tab.clicks, ['P1D9ZT7U'])

    async def test_unquoted_comma_price_is_one_keyword(self):
        tab = self.page('3-area select.html')
        self.config['area_auto_select']['area_keyword'] = '3,880'
        self.assertEqual(await self.select_area(tab), (True, False))
        self.assertEqual(tab.clicks, ['P1DA05GE'])

    async def test_shared_area_exclusions_support_semicolon(self):
        tab = self.page('3-area select.html')
        self.config['keyword_exclude'] = '"平面;2樓紫;2樓紅"'
        self.assertEqual(await self.select_area(tab), (True, False))
        self.assertEqual(tab.clicks, ['P1DA05HE'])

    async def test_shared_exclusions_support_nested_and_groups(self):
        tab = self.page('3-area select.html')
        self.config['keyword_exclude'] = '["2樓黃2E區", "3,880"]'
        self.config['area_auto_select']['area_keyword'] = '"2樓黃2E區3880元"'
        self.assertEqual(await self.select_area(tab), (False, False))
        self.assertEqual(tab.clicks, [])
        self.assertEqual(tab.reloads, 1)

    async def test_fallback_clicks_exactly_one_available_area(self):
        tab = self.page('3-area select.html')
        self.config['area_auto_fallback'] = True
        self.config['area_auto_select']['area_keyword'] = '"missing","also missing"'
        self.assertEqual(await self.select_area(tab), (True, False))
        self.assertEqual(tab.clicks, ['P1DA05KQ'])

    async def test_all_excluded_areas_retry_at_configured_interval(self):
        tab = self.page('3-area select.html')
        self.config['keyword_exclude'] = '"區"'
        self.assertEqual(await self.select_area(tab), (False, False))
        self.assertEqual(tab.clicks, [])
        self.assertEqual(tab.reloads, 1)
        self.wait.assert_awaited_once_with(1.75, self.config)
        self.mark.assert_called_once_with()

    async def test_pause_arriving_during_area_wait_prevents_reload(self):
        async def pause_during_wait(*_):
            self.pause.return_value = True
            return False

        self.wait.side_effect = pause_during_wait
        tab = Tab('')
        self.assertEqual(await self.select_area(tab), (False, False))
        self.assertEqual(tab.reloads, 0)
        self.mark.assert_not_called()

    async def test_pause_arriving_during_date_wait_prevents_reload(self):
        async def pause_during_wait(*_):
            self.pause.return_value = True
            return False

        self.wait.side_effect = pause_during_wait
        tab = Tab('')
        self.assertFalse(await self.select_date(tab))
        self.assertEqual(tab.reloads, 0)
        self.mark.assert_not_called()


if __name__ == '__main__':
    unittest.main()
