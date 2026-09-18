"""Regenerates the synthetic CSV fixtures used by the TypeScript SDK test suite.

The runtime tests exercise local CSV ingestion, header-alias detection, empty-source
rejection, and metric aggregation against three delivery-marketplace merchant export
files: an order-level export, a payout-level export with a descriptive alias header
row, and a header-only (empty) store-pause export. The fixtures were once captured
from real merchant exports; they are now fully synthetic so the repository never
carries third-party merchant data.

Everything in the output is obviously synthetic: store names are "Synthetic Store
NNN", payout references are "SYNTH..." sequences, and all amounts are round numbers.
The schemas (column names, alias description row, row counts, and per-row shapes)
match the original exports exactly, because the test suite asserts on them.

The generator is deterministic: a hard-coded seed drives every random choice, no
wall-clock or environment state is consulted, and no hash-ordered iteration is used.
Running it twice produces byte-identical files.

Usage (from the repository root):

    python3 scripts/generate_test_fixtures.py

The CSVs are written to packages/ts-sdk/test-fixtures/ by default. The test suite
asserts exact row counts (6097 order-export rows, 2026 payout-export rows after
alias-header skipping, 0 store-pause rows), so edit this script rather than the
generated files.
"""

from __future__ import annotations

import argparse
import hashlib
import random
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

SEED = 20260301

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "packages" / "ts-sdk" / "test-fixtures"

ORDERS_FILENAME = "synthetic_orders_march_2026.csv"
FINANCIAL_FILENAME = "synthetic_financial_march_2026.csv"
STORE_PAUSE_FILENAME = "synthetic_store_pause_empty.csv"

UTF8_BOM = "\ufeff"

# Row-count contract asserted by packages/ts-sdk/src/runtime_supports.test.ts and
# runtime_misc.test.ts. Do not change without updating the suite.
ORDER_ROW_COUNT = 1902
ITEM_ROW_COUNT = 4071
AD_SPEND_ROW_COUNT = 120
AD_CREDITS_ROW_COUNT = 4

STORES = ("Synthetic Store 001", "Synthetic Store 002")

# Column schemas, byte-identical to the original exports (the test suite resolves
# columns by these exact names, including the trailing spaces in "External ID "
# and "Total payout ").
ORDERS_HEADER = (
    "Store Name",
    "Store ID",
    "Order ID",
    "Workflow ID",
    "Item Name",
    "Item Priced By",
    "Unit Sold By",
    "Estimated Average Weight",
    "Requested Weight",
    "Final Weight",
    "Requested Count",
    "Final Count",
    "Requested Quantity",
    "Final Quantity",
    "Unit price",
    "External ID ",
    "Dining Mode",
    "Payment Mode",
    "Order Channel",
    "Order Status",
    "Order Date",
    "Order Accept Time",
    "Customer Uber-Membership Status",
    "Sales (excl. tax)",
    "Tax on Sales",
    "Sales (incl. tax)",
    "Order Error Adjustments",
    "Tax on Order Error Adjustments",
    "Order Error Adjustments (incl. tax)",
    "Price adjustments (excl. tax)",
    "Tax on Price Adjustments",
    "Offers on items (incl. tax)",
    "Tax On Offers on items",
    "Delivery Offer Redemptions (incl. tax)",
    "Tax On Delivery Offer Redemptions",
    "Offer Redemption Fee",
    "Bag Fee",
    "Marketing Adjustment",
    "Total Sales after Adjustments (incl tax)",
    "Marketplace Fee",
    "Marketplace fee %",
    "Tax on Marketplace Fee",
    "Delivery Network Fee",
    "Tax on Delivery Network Fee",
    "Order Processing Fee",
    "Delivery Fee",
    "Tax On Delivery Fee",
    "Tips",
    "Capital payments",
    "Container Deposit Fee",
    "Other payments description",
    "Other payments",
    "Marketplace Facilitator Tax Adjustment",
    "Marketplace Facilitator Tax",
    "Backup Withholding Tax",
    "Total payout ",
    "Payout Date",
    "Markup Amount",
    "Markup Tax",
    "Retailer Loyalty ID",
    "Payout reference ID",
)

FINANCIAL_HEADER = (
    "Store Name",
    "Store ID",
    "Order ID",
    "Workflow ID",
    "Dining Mode",
    "Payment Mode",
    "Order Channel",
    "Order Status",
    "Order Date",
    "Order Accept Time",
    "Customer Uber-Membership Status",
    "Sales (excl. tax)",
    "Tax on Sales",
    "Sales (incl. tax)",
    "Order Error Adjustments",
    "Tax on Order Error Adjustments",
    "Order Error Adjustments (incl. tax)",
    "Price adjustments (excl. tax)",
    "Tax on Price Adjustments",
    "Offers on items (incl. tax)",
    "Tax On Offers on items",
    "Delivery Offer Redemptions (incl. tax)",
    "Tax On Delivery Offer Redemptions",
    "Offer Redemption Fee",
    "Bag Fee",
    "Marketing Adjustment",
    "Total Sales after Adjustments (incl tax)",
    "Marketplace Fee",
    "Marketplace fee %",
    "Tax on Marketplace Fee",
    "Delivery Network Fee",
    "Tax on Delivery Network Fee",
    "Order Processing Fee",
    "Delivery Fee",
    "Tax On Delivery Fee",
    "Tips",
    "Capital payments",
    "Container Deposit Fee",
    "Other payments description",
    "Other payments",
    "Marketplace Facilitator Tax Adjustment",
    "Marketplace Facilitator Tax",
    "Backup Withholding Tax",
    "Total payout ",
    "Payout Date",
    "Markup Amount",
    "Markup Tax",
    "Retailer Loyalty ID",
    "Payout reference ID",
)

# Descriptive alias row that precedes the real header in the payout-level export.
# The SDK's CSV reader detects and skips exactly this shape (see
# looksLikeHeaderAliasRow in packages/ts-sdk/src/_runtime_helpers_c.ts); the suite
# asserts the resulting row count, so these descriptions must keep their original
# token overlap with FINANCIAL_HEADER. The trailing tab in "…on Merchant’s behalf"
# is part of the original format and must be preserved.
FINANCIAL_DESCRIPTION_ROW = (
    "Store name as per Uber Eats manager",
    "External store ID as per Uber Eats manager",
    "Order ID as per Uber Eats manager",
    "Unique ID to identify the order ",
    "The mode of order fulfillment whether it was delivery by courier via Uber network, "
    "delivery by merchant, Pick-up by customer or Dine-in",
    "Mode of payment used for order payment",
    "The platform from which the customer ordered, (i.e. iOS, Android, Uber Eats Web)",
    "Either: Completed (eater received food), Cancelled (order cancelled by eater or support), "
    "Refund (eater was refunded for order), or Unfulfilled (order was not able to be completed)",
    "Local date the order was placed, or local date of the original order placed for which "
    "there is a refund",
    "Local timestamp for when order was accepted by the merchant ",
    "Uber membership status of the customer who placed the order",
    "Total item sales excl tax ",
    "Tax on total item sales in the order",
    "Total item sales incl tax",
    "Amount merchants are responsible for refunding customers when they report order errors "
    "(excl tax)",
    "Tax Refund On Sales",
    "Amount merchants are responsible for refunding customers when they report order errors "
    "(incl tax)",
    "Adjustments merchants made to the price of items once an order has been placed (excl tax)",
    "Tax on in-store price adjustments",
    "Merchant promotions applied to the order",
    "Tax on merchant promotions applied to the order",
    "Merchant promotions applied to the delivery fee charged to Eaters",
    "Tax on merchant promotions applied to the delivery fee charged to Eaters",
    "Offer Redemption Fee",
    "Fee charged to eater by the merchant for the packaging material",
    "Amount merchant charges Uber for co-funded marketing campaigns. Varies depending on "
    "co-funding % for the campaign.",
    "Total item sales including promotions, adjustments and bag fee incl tax where applicable",
    "The fee Uber charges to merchant to make their store visible to potential customers, "
    "provide support and other related services ( %fee is applied to sub-total before "
    "discounts) ",
    "The % Marketplace fee Uber charges merchant",
    "Tax on Marketplace fee charged to merchant by Uber",
    "Fixed Fee charged to merchant by Uber for using Ubers delivery network ",
    "Tax on delivery network fee charged to merchant by Uber",
    "A flat % fee on the basket charged by Uber to merchants for processing every order ",
    "Where delivery fee is greater than cost of delivery, this is equal to (delivery fee "
    "minus the cost of delivery) where applicable",
    "Tax on service fee charged by merchants to eaters",
    "For merchants who perform their own delivery, the tip from the Eater to the courier",
    "Amount directed to Merchant Capital payments",
    "This is the amount collected for the container deposit fee set in the catalog/menu",
    "Description of adhoc one-time payments or charges from Uber to the merchant",
    "All miscellaneous payments like Ad payments, Ad credits etc. inclusive of tax",
    "Tax Adjustment on Marketplace Facilitator Tax for this order",
    "Sales tax Uber Eats is required to pay in jurisdictions with marketplace facilitator "
    "laws ",
    "As required by the IRS, a % withheld from payments if the EIN/TIN is missing or does "
    "not match IRS records.",
    "Total payout associated with this order (negative if associated with a refund)  Sales + "
    "Adjustments - promotions + marketing adjustment + Bag fee + delivery fee (self "
    "delivery) + tips (self-delivery) - marketplace fee +/- Other payments - marketplace "
    "facilitator tax  (incl tax where applicable)",
    "Date payout initiated by Uber (generally the Monday following the prior week)",
    "Amount commercially agreed to between Merchant and Uber added on a per item basis and "
    "charged to the Eater on Merchant’s behalf\t",
    "Applicable taxes due on the Markup Amount",
    "This is the ID from retailers, used to identify retailer loyalty customers",
    "The reference ID for identifying the payout related to this order in the Payout Summary "
    "Report CSV",
)

STORE_PAUSE_HEADER = (
    "Store",
    "External Store ID",
    "City",
    "Country",
    "Country Code",
    "Pause Start",
    "Pause Duration",
    "Reason For Pausing",
)

# Exact marginal distributions from the original exports, so the synthetic files
# carry the same mix of shapes and edge cases (refunds, cancellations, promos,
# multi-item orders, per-store volume skew).
STATUS_COUNTS = {"Completed": 1849, "Refund": 42, "Cancelled": 8, "Unfulfilled": 3}
CHANNEL_COUNTS = {
    "UberEats iOS": 1672,
    "UberEats Android": 80,
    "Postmates iOS": 60,
    "UberEats Web": 40,
    "UberEats Unknown": 38,
    "Postmates Web": 4,
    "Postmates Unknown": 4,
    "Postmates Android": 2,
    "UberEats Online Ordering Web": 2,
}
STORE_COUNTS = {STORES[0]: 1265, STORES[1]: 637}
MEMBERSHIP_COUNTS = {"Uber One member": 1432, "Non-member": 470}
DINING_MODE_COUNTS = {
    "Delivery - Partner Using Uber App": 1632,
    "Pickup": 270,
}
# Items per non-refund order; refund orders have no item rows.
ITEMS_PER_ORDER_COUNTS = {
    1: 746, 2: 556, 3: 292, 4: 134, 5: 64, 6: 37, 7: 13, 8: 9, 9: 2, 10: 2, 11: 4, 14: 1,
}
ITEM_QUANTITY_COUNTS = {1: 2189, 2: 1835, 3: 23, 4: 20, 6: 4}
COMPLETED_WITH_PROMO_COUNT = 1277

# Synthetic menu: 20 items at round prices ($10-$40). Orders draw from this menu,
# so item names repeat across orders like a real export.
MENU = tuple(
    (f"SYNTHETIC ITEM {index:03d}", price_cents)
    for index, price_cents in enumerate(
        [1000, 1200, 1600, 2000, 2400, 2800, 3200, 4000] * 2 + [1000, 2000, 3000, 4000],
        start=1,
    )
)

TAX_RATE_DIVISOR = 10  # 10% flat synthetic tax; round by construction.
PROMO_BASES_CENTS = (500, 1000, 1500, 2000, 2500)
REDEMPTION_FEE_CENTS = -100

# Two ad-spend rows per store per day for days 1-30 (2 stores x 2 rows x 30 days
# = 120 rows), each at its own round amount.
AD_SPEND_AMOUNTS_CENTS = {STORES[0]: (-5000, -3000), STORES[1]: (-2500, -1500)}
AD_CREDITS_AMOUNT_CENTS = 2500
AD_CREDITS_DAYS = (7, 14, 21, 28)

MARCH_DAYS = 31
ZERO = "0"


def fmt_cents(cents: int) -> str:
    """Render integer cents the way the original exports render amounts: no
    trailing-zero padding ("120", "8.4", "-25.75")."""
    sign = "-" if cents < 0 else ""
    quotient, remainder = divmod(abs(cents), 100)
    if remainder == 0:
        return f"{sign}{quotient}"
    return f"{sign}{quotient}.{remainder:02d}".rstrip("0")


def fmt_date(day: date) -> str:
    """M/D/YY without zero padding, matching the original exports ("3/1/26")."""
    return f"{day.month}/{day.day}/{day.year % 100:02d}"


def next_monday(day: date) -> date:
    """First Monday strictly after the given day (the payout cadence)."""
    delta = (7 - day.weekday()) % 7
    return day + timedelta(days=delta if delta else 7)


def expand_counts(counts: dict[str, int] | dict[int, int], rng: random.Random) -> list:
    """Expand an exact count map into a shuffled pool (deterministic via rng)."""
    pool = []
    for key in sorted(counts, key=str):
        pool.extend([key] * counts[key])
    rng.shuffle(pool)
    return pool


def render_csv_line(cells: list[str] | tuple[str, ...]) -> str:
    """Render one CSV line with minimal quoting, matching the original exports:
    a cell is quoted only when it contains a comma or a double quote."""
    rendered = []
    for cell in cells:
        if "," in cell or '"' in cell:
            rendered.append('"' + cell.replace('"', '""') + '"')
        else:
            rendered.append(cell)
    return ",".join(rendered)


@dataclass
class Item:
    name: str
    quantity: int
    unit_price_cents: int
    external_id: str

    @property
    def total_cents(self) -> int:
        return self.quantity * self.unit_price_cents


@dataclass
class Order:
    store: str
    order_id: str
    workflow_id: str
    dining_mode: str
    channel: str
    status: str
    day: date
    accept_time: str
    membership: str
    promo: bool
    refund_base_cents: int
    items: list[Item] = field(default_factory=list)

    @property
    def payout_day(self) -> date:
        return next_monday(self.day)

    @property
    def sales_excl_cents(self) -> int:
        return sum(item.total_cents for item in self.items)

    def promo_base_cents(self) -> int:
        """Round promo amount, bounded so the adjusted total stays positive."""
        sales = self.sales_excl_cents
        eligible = [base for base in PROMO_BASES_CENTS if 2 * base <= sales]
        base = eligible[self.workflow_sequence % len(eligible)] if eligible else 0
        return base

    @property
    def workflow_sequence(self) -> int:
        return int(self.workflow_id.rsplit("-", 1)[1])


def build_payout_refs(
    keys: list[tuple[str, date]],
) -> dict[tuple[str, date], str]:
    """Assign one "SYNTH..." payout reference per (store, payout day), in
    deterministic sorted order."""
    unique = sorted(set(keys), key=lambda pair: (pair[1].toordinal(), pair[0]))
    return {key: f"SYNTH{position:012d}" for position, key in enumerate(unique, start=1)}


def build_orders(rng: random.Random) -> list[Order]:
    """Create the shared synthetic order population used by both exports."""
    statuses = expand_counts(STATUS_COUNTS, rng)
    channels = expand_counts(CHANNEL_COUNTS, rng)
    stores = expand_counts(STORE_COUNTS, rng)
    memberships = expand_counts(MEMBERSHIP_COUNTS, rng)
    dining_modes = expand_counts(DINING_MODE_COUNTS, rng)
    promo_pool = expand_counts(
        {
            "promo": COMPLETED_WITH_PROMO_COUNT,
            "no_promo": STATUS_COUNTS["Completed"] - COMPLETED_WITH_PROMO_COUNT,
        },
        rng,
    )
    item_count_pool = expand_counts(ITEMS_PER_ORDER_COUNTS, rng)
    quantity_pool = expand_counts(ITEM_QUANTITY_COUNTS, rng)

    orders: list[Order] = []
    item_sequence = 0
    for position in range(ORDER_ROW_COUNT):
        status = statuses[position]
        workflow_id = f"00000000-0000-4000-8000-{position + 1:012d}"
        hour = rng.randint(11, 23)
        minute = rng.randint(0, 59)
        accept_time = f"{hour % 12 or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"
        promo = status == "Completed" and promo_pool.pop() == "promo"
        if status == "Cancelled":
            promo = position % 2 == 0
        order = Order(
            store=stores[position],
            order_id=f"#A{position + 1:04d}",
            workflow_id=workflow_id,
            dining_mode=dining_modes[position],
            channel=channels[position],
            status=status,
            day=date(2026, 3, position % MARCH_DAYS + 1),
            accept_time=accept_time,
            membership=memberships[position],
            promo=promo,
            refund_base_cents=(position % 7 + 1) * 1000 if status == "Refund" else 0,
        )
        if status != "Refund":
            for _ in range(item_count_pool.pop()):
                name, price_cents = MENU[rng.randrange(len(MENU))]
                item_sequence += 1
                order.items.append(
                    Item(
                        name=name,
                        quantity=quantity_pool.pop(),
                        unit_price_cents=price_cents,
                        external_id=f"AAAAAAAA-0000-4000-8000-{item_sequence:012d}",
                    )
                )
        orders.append(order)
    return orders


def order_money_columns(order: Order) -> dict[str, str]:
    """Money-column values for one order row, internally consistent in cents."""
    if order.status == "Refund":
        base = order.refund_base_cents
        tax = base // TAX_RATE_DIVISOR
        return {
            "Sales (excl. tax)": ZERO,
            "Tax on Sales": ZERO,
            "Sales (incl. tax)": ZERO,
            "Order Error Adjustments": fmt_cents(-base),
            "Tax on Order Error Adjustments": fmt_cents(-tax),
            "Order Error Adjustments (incl. tax)": fmt_cents(-(base + tax)),
            "Price adjustments (excl. tax)": ZERO,
            "Tax on Price Adjustments": ZERO,
            "Offers on items (incl. tax)": ZERO,
            "Tax On Offers on items": ZERO,
            "Delivery Offer Redemptions (incl. tax)": ZERO,
            "Tax On Delivery Offer Redemptions": ZERO,
            "Offer Redemption Fee": ZERO,
            "Bag Fee": ZERO,
            "Marketing Adjustment": ZERO,
            "Total Sales after Adjustments (incl tax)": ZERO,
            "Marketplace Fee": ZERO,
            "Tax on Marketplace Fee": ZERO,
            "Delivery Network Fee": ZERO,
            "Tax on Delivery Network Fee": ZERO,
            "Order Processing Fee": ZERO,
            "Delivery Fee": ZERO,
            "Tax On Delivery Fee": ZERO,
            "Tips": ZERO,
            "Capital payments": ZERO,
            "Container Deposit Fee": ZERO,
            "Other payments": ZERO,
            "Marketplace Facilitator Tax Adjustment": ZERO,
            "Marketplace Facilitator Tax": fmt_cents(tax),
            "Backup Withholding Tax": ZERO,
            "Total payout ": fmt_cents(-base),
            "Markup Amount": ZERO,
            "Markup Tax": ZERO,
        }

    sales = order.sales_excl_cents
    tax = sales // TAX_RATE_DIVISOR
    incl = sales + tax
    offers_incl = offers_tax = redemption = marketing = 0
    if order.promo:
        promo_base = order.promo_base_cents()
        offers_tax = -(promo_base // TAX_RATE_DIVISOR)
        offers_incl = -(promo_base - offers_tax)
        redemption = REDEMPTION_FEE_CENTS
        marketing = promo_base // 4
    total_after = incl + offers_incl + offers_tax + redemption + marketing
    if order.dining_mode == "Pickup":
        fee_pct = 6
    elif order.channel.startswith("Postmates"):
        fee_pct = 24
    else:
        fee_pct = 20
    marketplace_fee = -(total_after * fee_pct // 100)
    facilitator_tax = -(tax + offers_tax)
    payout = total_after + marketplace_fee + facilitator_tax
    return {
        "Sales (excl. tax)": fmt_cents(sales),
        "Tax on Sales": fmt_cents(tax),
        "Sales (incl. tax)": fmt_cents(incl),
        "Order Error Adjustments": ZERO,
        "Tax on Order Error Adjustments": ZERO,
        "Order Error Adjustments (incl. tax)": ZERO,
        "Price adjustments (excl. tax)": ZERO,
        "Tax on Price Adjustments": ZERO,
        "Offers on items (incl. tax)": fmt_cents(offers_incl),
        "Tax On Offers on items": fmt_cents(offers_tax),
        "Delivery Offer Redemptions (incl. tax)": ZERO,
        "Tax On Delivery Offer Redemptions": ZERO,
        "Offer Redemption Fee": fmt_cents(redemption),
        "Bag Fee": ZERO,
        "Marketing Adjustment": fmt_cents(marketing),
        "Total Sales after Adjustments (incl tax)": fmt_cents(total_after),
        "Marketplace Fee": fmt_cents(marketplace_fee),
        "Marketplace fee %": str(fee_pct),
        "Tax on Marketplace Fee": ZERO,
        "Delivery Network Fee": ZERO,
        "Tax on Delivery Network Fee": ZERO,
        "Order Processing Fee": ZERO,
        "Delivery Fee": ZERO,
        "Tax On Delivery Fee": ZERO,
        "Tips": ZERO,
        "Capital payments": ZERO,
        "Container Deposit Fee": ZERO,
        "Other payments": ZERO,
        "Marketplace Facilitator Tax Adjustment": ZERO,
        "Marketplace Facilitator Tax": fmt_cents(facilitator_tax),
        "Backup Withholding Tax": ZERO,
        "Total payout ": fmt_cents(payout),
        "Markup Amount": ZERO,
        "Markup Tax": ZERO,
    }


def order_row(order: Order, header: tuple[str, ...], payout_ref: str) -> list[str]:
    row = [""] * len(header)
    index = {name: position for position, name in enumerate(header)}

    def set_value(column: str, value: str) -> None:
        if column in index:
            row[index[column]] = value

    set_value("Store Name", order.store)
    set_value("Order ID", order.order_id)
    set_value("Workflow ID", order.workflow_id)
    set_value("Dining Mode", order.dining_mode)
    set_value("Payment Mode", "Digital")
    set_value("Order Channel", order.channel)
    set_value("Order Status", order.status)
    set_value("Order Date", fmt_date(order.day))
    set_value("Order Accept Time", order.accept_time)
    set_value("Customer Uber-Membership Status", order.membership)
    for column, value in order_money_columns(order).items():
        set_value(column, value)
    set_value("Payout Date", fmt_date(order.payout_day))
    set_value("Payout reference ID", payout_ref)
    return row


def item_row(order: Order, item: Item) -> list[str]:
    row = [""] * len(ORDERS_HEADER)
    index = {name: position for position, name in enumerate(ORDERS_HEADER)}
    total = item.total_cents
    tax = total // TAX_RATE_DIVISOR
    row[index["Workflow ID"]] = order.workflow_id
    row[index["Item Name"]] = item.name
    row[index["Item Priced By"]] = "Count"
    row[index["Unit Sold By"]] = "Count"
    row[index["Estimated Average Weight"]] = ZERO
    row[index["Requested Weight"]] = ZERO
    row[index["Final Weight"]] = ZERO
    row[index["Requested Count"]] = str(item.quantity)
    row[index["Final Count"]] = str(item.quantity)
    row[index["Requested Quantity"]] = str(item.quantity)
    row[index["Final Quantity"]] = str(item.quantity)
    row[index["Unit price"]] = fmt_cents(item.unit_price_cents)
    row[index["External ID "]] = item.external_id
    row[index["Dining Mode"]] = order.dining_mode
    row[index["Order Channel"]] = order.channel
    row[index["Order Status"]] = order.status
    row[index["Order Date"]] = fmt_date(order.day)
    row[index["Order Accept Time"]] = order.accept_time
    row[index["Sales (excl. tax)"]] = fmt_cents(total)
    row[index["Tax on Sales"]] = fmt_cents(tax)
    row[index["Sales (incl. tax)"]] = fmt_cents(total + tax)
    row[index["Order Error Adjustments"]] = ZERO
    row[index["Tax on Order Error Adjustments"]] = ZERO
    row[index["Order Error Adjustments (incl. tax)"]] = ZERO
    return row


# Money columns rendered as explicit "0" on adjustment rows, matching the original
# exports (other non-applicable columns stay empty).
ADJUSTMENT_ZERO_COLUMNS = (
    "Sales (excl. tax)",
    "Tax on Sales",
    "Sales (incl. tax)",
    "Order Error Adjustments",
    "Tax on Order Error Adjustments",
    "Order Error Adjustments (incl. tax)",
    "Price adjustments (excl. tax)",
    "Tax on Price Adjustments",
    "Offers on items (incl. tax)",
    "Tax On Offers on items",
    "Delivery Offer Redemptions (incl. tax)",
    "Tax On Delivery Offer Redemptions",
    "Offer Redemption Fee",
    "Bag Fee",
    "Marketing Adjustment",
    "Total Sales after Adjustments (incl tax)",
    "Marketplace Fee",
    "Tax on Marketplace Fee",
    "Delivery Network Fee",
    "Tax on Delivery Network Fee",
    "Order Processing Fee",
    "Delivery Fee",
    "Tax On Delivery Fee",
    "Tips",
    "Capital payments",
    "Container Deposit Fee",
    "Marketplace Facilitator Tax Adjustment",
    "Marketplace Facilitator Tax",
    "Backup Withholding Tax",
    "Markup Amount",
    "Markup Tax",
)


@dataclass(frozen=True)
class Adjustment:
    store: str
    kind: str  # "Ad Spend" or "Ad Credits"
    day: date
    amount_cents: int

    @property
    def payout_day(self) -> date:
        return next_monday(self.day)


def adjustment_row(adjustment: Adjustment, header: tuple[str, ...], payout_ref: str) -> list[str]:
    row = [""] * len(header)
    index = {name: position for position, name in enumerate(header)}
    row[index["Store Name"]] = adjustment.store
    row[index["Order Channel"]] = "UberEats Unknown"
    row[index["Order Date"]] = fmt_date(adjustment.day)
    for column in ADJUSTMENT_ZERO_COLUMNS:
        if column in index:
            row[index[column]] = ZERO
    row[index["Other payments description"]] = adjustment.kind
    row[index["Other payments"]] = fmt_cents(adjustment.amount_cents)
    row[index["Total payout "]] = fmt_cents(adjustment.amount_cents)
    row[index["Payout Date"]] = fmt_date(adjustment.payout_day)
    row[index["Payout reference ID"]] = payout_ref
    return row


def build_adjustments() -> list[Adjustment]:
    """120 ad-spend rows (two per store for days 1-30) and 4 ad-credit rows."""
    adjustments: list[Adjustment] = []
    for day_number in range(1, 31):
        day = date(2026, 3, day_number)
        for store in STORES:
            for amount_cents in AD_SPEND_AMOUNTS_CENTS[store]:
                adjustments.append(
                    Adjustment(
                        store=store,
                        kind="Ad Spend",
                        day=day,
                        amount_cents=amount_cents,
                    )
                )
    for position, day_number in enumerate(AD_CREDITS_DAYS):
        adjustments.append(
            Adjustment(
                store=STORES[position % len(STORES)],
                kind="Ad Credits",
                day=date(2026, 3, day_number),
                amount_cents=AD_CREDITS_AMOUNT_CENTS,
            )
        )
    return adjustments


def write_csv(path: Path, lines: list[str], *, with_bom: bool) -> None:
    text = "\n".join(lines) + "\n"
    if with_bom:
        text = UTF8_BOM + text
    path.write_text(text, encoding="utf-8", newline="")


def validate_rows(rows: list[list[str]], width: int, context: str) -> None:
    """Fail fast on any shape that would break byte-level format parity."""
    for position, row in enumerate(rows, start=1):
        if len(row) != width:
            raise ValueError(f"{context}: row {position} has {len(row)} cells, expected {width}")
        for cell in row:
            if any(token in cell for token in ('"', "\n", "\r")):
                raise ValueError(
                    f"{context}: row {position} contains a cell requiring quoting: {cell!r}"
                )


def generate(output_dir: Path) -> list[tuple[str, int, int, str]]:
    """Generate all three fixtures; return (filename, data rows, bytes, sha256)."""
    rng = random.Random(SEED)
    orders = build_orders(rng)
    adjustments = build_adjustments()

    if sum(len(order.items) for order in orders) != ITEM_ROW_COUNT:
        raise ValueError("internal error: item pool does not produce the expected row count")
    if len(adjustments) != AD_SPEND_ROW_COUNT + AD_CREDITS_ROW_COUNT:
        raise ValueError("internal error: unexpected adjustment row count")

    payout_keys = [(order.store, order.payout_day) for order in orders]
    payout_keys += [(adjustment.store, adjustment.payout_day) for adjustment in adjustments]
    payout_refs = build_payout_refs(payout_keys)

    # Emit day by day — adjustment rows first, then each order followed by its
    # item rows — mirroring the layout of the original exports.
    adjustments_by_day: dict[int, list[Adjustment]] = {}
    for adjustment in adjustments:
        adjustments_by_day.setdefault(adjustment.day.day, []).append(adjustment)
    orders_by_day: dict[int, list[Order]] = {}
    for order in orders:
        orders_by_day.setdefault(order.day.day, []).append(order)

    orders_lines = [render_csv_line(ORDERS_HEADER)]
    financial_lines = [
        render_csv_line(FINANCIAL_DESCRIPTION_ROW),
        render_csv_line(FINANCIAL_HEADER),
    ]
    for day_number in range(1, MARCH_DAYS + 1):
        for adjustment in adjustments_by_day.get(day_number, []):
            ref = payout_refs[(adjustment.store, adjustment.payout_day)]
            orders_lines.append(render_csv_line(adjustment_row(adjustment, ORDERS_HEADER, ref)))
            financial_lines.append(
                render_csv_line(adjustment_row(adjustment, FINANCIAL_HEADER, ref))
            )
        for order in orders_by_day.get(day_number, []):
            ref = payout_refs[(order.store, order.payout_day)]
            orders_lines.append(render_csv_line(order_row(order, ORDERS_HEADER, ref)))
            financial_lines.append(render_csv_line(order_row(order, FINANCIAL_HEADER, ref)))
            for item in order.items:
                orders_lines.append(render_csv_line(item_row(order, item)))

    parsed_orders_rows = [line.split(",") for line in orders_lines[1:]]
    parsed_financial_rows = [line.split(",") for line in financial_lines[2:]]
    validate_rows(parsed_orders_rows, len(ORDERS_HEADER), ORDERS_FILENAME)
    validate_rows(parsed_financial_rows, len(FINANCIAL_HEADER), FINANCIAL_FILENAME)

    expected_orders_rows = (
        ORDER_ROW_COUNT + ITEM_ROW_COUNT + AD_SPEND_ROW_COUNT + AD_CREDITS_ROW_COUNT
    )
    expected_financial_rows = ORDER_ROW_COUNT + AD_SPEND_ROW_COUNT + AD_CREDITS_ROW_COUNT
    if len(orders_lines) - 1 != expected_orders_rows:
        raise ValueError(f"{ORDERS_FILENAME}: expected {expected_orders_rows} data rows")
    if len(financial_lines) - 2 != expected_financial_rows:
        raise ValueError(f"{FINANCIAL_FILENAME}: expected {expected_financial_rows} data rows")

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = [
        (ORDERS_FILENAME, expected_orders_rows, orders_lines, True),
        (FINANCIAL_FILENAME, expected_financial_rows, financial_lines, True),
        (STORE_PAUSE_FILENAME, 0, [render_csv_line(STORE_PAUSE_HEADER)], False),
    ]
    summary: list[tuple[str, int, int, str]] = []
    for filename, data_rows, lines, with_bom in outputs:
        path = output_dir / filename
        write_csv(path, lines, with_bom=with_bom)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        summary.append((filename, data_rows, path.stat().st_size, digest))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="directory to write the CSV fixtures into "
        f"(default: {DEFAULT_OUTPUT_DIR.relative_to(REPO_ROOT)})",
    )
    args = parser.parse_args()

    summary = generate(args.output_dir)
    for filename, data_rows, byte_count, digest in summary:
        print(f"{filename}: {data_rows} data rows, {byte_count} bytes, sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
