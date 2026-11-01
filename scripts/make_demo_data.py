"""Generate a synthetic sales CSV with the same columns as Online Retail II.

All data is randomly generated (fixed seed), so results are repeatable.
Usage: python scripts/make_demo_data.py [output_path]
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/demo_sales.csv")
rng = np.random.default_rng(42)

# Products: a long tail where a few items sell far more than the rest.
ADJ = ["VINTAGE", "RETRO", "PINK", "BLUE", "GREEN", "WOODEN", "GLASS", "CERAMIC", "METAL", "FLORAL", "STRIPED", "SMALL", "LARGE", "HANGING"]
ITEM = ["MUG", "CANDLE HOLDER", "LANTERN", "CUSHION COVER", "TEA TOWEL", "PHOTO FRAME", "STORAGE TIN", "BUNTING", "NOTEBOOK", "DOOR SIGN", "LUNCH BAG", "JAR SET", "CLOCK", "TRAY"]
names = [f"{a} {i}" for a in ADJ for i in ITEM][:200]
codes = [f"{22000 + n}" for n in range(len(names))]
price = np.round(np.clip(rng.lognormal(1.0, 0.7, len(names)), 0.5, 40), 2)
pop = 1 / np.arange(1, len(names) + 1) ** 0.9
pop /= pop.sum()
seasonal_item = rng.random(len(names)) < 0.15  # some items sell mainly in Q4

# Customers: each is active for a window, so some become "at risk" or "lost".
N = 1400
days = pd.date_range("2010-01-01", "2011-12-31", freq="D")
start = rng.integers(0, len(days) - 30, N)
life = rng.integers(60, 800, N)
end = np.minimum(start + life, len(days) - 1)
cust_ids = 12000 + np.arange(N)
weight = 1 / np.arange(1, N + 1) ** 0.7  # a few big buyers
rng.shuffle(weight)
country = rng.choice(
    ["United Kingdom", "Germany", "France", "EIRE", "Netherlands", "Spain", "Australia"],
    N, p=[0.86, 0.04, 0.035, 0.02, 0.015, 0.015, 0.015],
)

weekday = np.array([1.0, 1.1, 1.1, 1.15, 0.95, 0.35, 0.6])  # Mon..Sun
hours = np.arange(7, 20)
hour_p = np.array([1, 3, 6, 9, 10, 9, 8, 8, 7, 5, 3, 2, 1], float)
hour_p /= hour_p.sum()

rows = []
invoice = 500000
for d, day in enumerate(days):
    month_factor = {10: 1.35, 11: 1.7, 12: 1.2, 1: 0.8, 2: 0.85}.get(day.month, 1.0)
    growth = 1 + 0.35 * d / len(days)
    n_orders = rng.poisson(12 * growth * month_factor * weekday[day.dayofweek])
    active = np.where((start <= d) & (end >= d))[0]
    if n_orders == 0 or len(active) == 0:
        continue
    w = weight[active] / weight[active].sum()
    for _ in range(n_orders):
        invoice += 1
        guest = rng.random() < 0.14  # no customer ID
        c = int(rng.choice(active, p=w))
        when = day + pd.Timedelta(hours=int(rng.choice(hours, p=hour_p)), minutes=int(rng.integers(0, 60)))
        p = pop.copy()
        if day.month >= 10:
            p[seasonal_item] *= 4
        else:
            p[seasonal_item] *= 0.3
        p /= p.sum()
        lines = rng.choice(len(names), size=int(min(rng.geometric(0.22), 25)), replace=False, p=p)
        order = []
        for i in lines:
            qty = int(rng.choice([1, 2, 3, 4, 6, 12, 24], p=[0.28, 0.2, 0.12, 0.1, 0.14, 0.12, 0.04]))
            order.append([str(invoice), codes[i], names[i], qty, when, float(price[i]),
                          "" if guest else f"{cust_ids[c]}.0", "United Kingdom" if guest else country[c]])
        if rng.random() < 0.18:
            order.append([str(invoice), "POST", "POSTAGE", 1, when, 18.0, order[0][6], order[0][7]])
        rows += order
        if rng.random() < 0.04:  # a cancellation of part of this order
            invoice += 1
            for r in order[: max(1, len(order) // 2)]:
                rows.append([f"C{invoice}", r[1], r[2], -r[3], when + pd.Timedelta(days=int(rng.integers(1, 15))), r[5], r[6], r[7]])
        if rng.random() < 0.003:  # a data-entry error: zero price
            rows.append([str(invoice), codes[0], names[0], 5, when, 0.0, order[0][6], order[0][7]])

df = pd.DataFrame(rows, columns=["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Customer ID", "Country"])
dupes = df.sample(40, random_state=1)  # a few exact duplicate rows
df = pd.concat([df, dupes]).sort_values("InvoiceDate", kind="stable")
OUT.parent.mkdir(parents=True, exist_ok=True)
df.to_csv(OUT, index=False)

print(f"Wrote {OUT}: {len(df):,} rows, {OUT.stat().st_size / 1e6:.1f} MB")