# KHAM offline DOM fixtures

These are small, sanitized test fixtures derived from the locally saved KHAM
purchase samples supplied for this change. They are deliberately trimmed and
partly reauthored selector examples, not complete archived website pages. Tests
run from a fresh clone without the private `specs/` directory.

- `2-date select.html` keeps the four date rows, public performance/product IDs,
  date text, ticket labels, and order-button attributes.
- `3-area select.html` keeps seven representative area rows in their original
  order, including sold-out inventory, numeric stock 100/30/11, comma-formatted
  prices, and the extra `filter-ready` class that broke the former selector.
- `4-seat select.html` and `5-add to cart.html` retain the saved ticket-type
  buttons, CAPTCHA input, add-to-cart button, and a few original seat cells.
  The seat table is reduced and reassembled: an originally adjacent available
  pair, any selected cell, and the saved `SeatAddCart` cells. It is not a full
  seat map. The latter fixture also reproduces the success dialog structure.
- `2026-EUNHYUK.html` reproduces only the saved hidden presale notice and its
  dialog selectors.
- `6-cart page.html` reproduces the order/header/total structure using a fictional
  event name and venue. `PKNO` is the synthetic value `OFFLINE_ORDER_001`.
  Public performance/product IDs are retained solely for parser assertions.

No account information, addresses, cookies, session/order tokens, viewstate,
analytics, images, external resources, or original JavaScript are included.
Original handler strings needed as selector evidence are stored as inert
`data-original-onclick` attributes. The selection unit-test double restores
those attributes in a non-executing HTML parser. Browser tests sanitize fixtures
again, and only test-owned stub handlers are installed when needed.

The computer-seating page and two-day purchase routes are synthetic DOM defined
inline in `test_kham_browser.py`. Browser tests use an isolated temporary profile,
a dead proxy, blocked DNS, and CDP offline mode; they never purchase live tickets.
Passing tests verifies the covered selectors and controller flow, not the final
DOM or server behavior at a future live sale.
