import io
import os

import pandas as pd

MAX_BYTES = int(os.getenv("UPLOAD_MAX_MB", "25")) * 1024 * 1024

ALIASES = {
    "invoice": {"invoice", "invoiceno", "invoicenumber", "orderid", "order"},
    "stock_code": {"stockcode", "sku", "productid", "productcode"},
    "description": {"description", "product", "productname", "item"},
    "quantity": {"quantity", "qty", "units"},
    "invoice_date": {"invoicedate", "date", "orderdate", "datetime"},
    "price": {"price", "unitprice", "unitcost"},
    "customer_id": {"customerid", "customer", "clientid"},
    "country": {"country", "region"},
}
REQUIRED = ["description", "quantity", "invoice_date", "price"]

# Stock codes in this dataset that are fees or adjustments, not products.
NON_PRODUCT_CODES = {
    "POST", "D", "M", "DOT", "C2", "CRUK", "BANK CHARGES", "AMAZONFEE",
    "ADJUST", "ADJUST2", "S", "B", "TEST001", "TEST002", "PADS",
}


class CsvError(ValueError):
    """Raised when an uploaded file can't be used."""


def normalize(name):
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def read_csv(file, nrows=None):
    """Read a CSV as text. With nrows, only the first ~1 MB is loaded."""
    raw = file.read(1_000_000) if nrows else file.read()
    file.seek(0)
    if nrows and len(raw) == 1_000_000:
        raw = raw[: raw.rfind(b"\n")]  # drop a possibly cut-off last line
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=encoding, dtype=str, nrows=nrows)
        except UnicodeDecodeError:
            continue
        except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            raise CsvError("This file could not be read as a CSV.") from exc
    raise CsvError("This file could not be read as a CSV.")


def count_rows(file):
    """Count data rows by streaming, without loading the file into memory."""
    file.seek(0)
    lines = sum(chunk.count(b"\n") for chunk in iter(lambda: file.read(1024 * 1024), b""))
    file.seek(0)
    return max(lines - 1, 0)


def map_columns(columns):
    mapping = {}
    for col in columns:
        key = normalize(col)
        for canonical, names in ALIASES.items():
            if key in names and canonical not in mapping:
                mapping[canonical] = col
    return mapping


def validate_csv(file):
    if file.size > MAX_BYTES:
        raise CsvError(f"File is too large (max {MAX_BYTES // 1024 // 1024} MB).")
    df = read_csv(file, nrows=2000)
    if df.empty:
        raise CsvError("The file has no rows.")

    mapping = map_columns(df.columns)
    missing = [c for c in REQUIRED if c not in mapping]
    if missing:
        raise CsvError(
            f"Missing required columns: {', '.join(missing)}. "
            f"Found: {', '.join(map(str, df.columns))}."
        )

    sample = df.head(1000)
    for key in ("quantity", "price"):
        if pd.to_numeric(sample[mapping[key]], errors="coerce").notna().mean() < 0.9:
            raise CsvError(f"Column '{mapping[key]}' should contain numbers.")
    if pd.to_datetime(sample[mapping["invoice_date"]], errors="coerce").notna().mean() < 0.9:
        raise CsvError(f"Column '{mapping['invoice_date']}' should contain dates.")
    return count_rows(file), mapping


def pick(df, mapping, key):
    return df[mapping[key]] if key in mapping else pd.Series(pd.NA, index=df.index)


def analyze(file, mapping):
    """Clean the sales data and return a JSON-friendly summary."""
    df = read_csv(file)
    invoice = pick(df, mapping, "invoice")
    if "invoice" not in mapping:
        invoice = pd.Series(df.index.astype(str), index=df.index)

    data = pd.DataFrame({
        "invoice": invoice.astype(str).str.strip(),
        "stock": pick(df, mapping, "stock_code").astype(str).str.strip().str.upper(),
        "description": pick(df, mapping, "description").astype("string").str.strip(),
        "quantity": pd.to_numeric(df[mapping["quantity"]], errors="coerce"),
        "date": pd.to_datetime(df[mapping["invoice_date"]], errors="coerce"),
        "price": pd.to_numeric(df[mapping["price"]], errors="coerce"),
        "customer": pick(df, mapping, "customer_id"),
        "country": pick(df, mapping, "country"),
    })

    # Measure cancellations before they are removed.
    total_invoices = data["invoice"].nunique()
    is_cancel = data["invoice"].str.upper().str.startswith("C")
    cancelled_invoices = data.loc[is_cancel, "invoice"].nunique()
    cancelled_value = float((data["quantity"] * data["price"])[is_cancel].abs().sum())

    raw_rows = len(data)
    steps = []

    def drop(label, mask):
        nonlocal data
        steps.append({"label": label, "rows": int(mask.sum())})
        data = data[~mask]

    drop("Unreadable dates, quantities or prices", data[["quantity", "date", "price"]].isna().any(axis=1))
    drop("Cancelled invoices (start with C)", data["invoice"].str.upper().str.startswith("C"))
    drop("Zero or negative quantity", data["quantity"] <= 0)
    drop("Zero or negative price", data["price"] <= 0)
    drop("Non-product codes (postage, fees, adjustments)",
         data["stock"].isin(NON_PRODUCT_CODES) | data["stock"].str.startswith("GIFT"))
    drop("Missing description", data["description"].fillna("").eq(""))
    drop("Exact duplicate rows", data.duplicated())

    if data.empty:
        raise CsvError("No valid rows remain after cleaning.")

    data = data.assign(revenue=data["quantity"] * data["price"])
    revenue = float(data["revenue"].sum())
    orders = int(data["invoice"].nunique())

    kpis = {
        "revenue": round(revenue, 2),
        "orders": orders,
        "customers": int(data["customer"].dropna().nunique()),
        "units": int(data["quantity"].sum()),
        "avg_order_value": round(revenue / orders, 2),
        "first_date": data["date"].min().date().isoformat(),
        "last_date": data["date"].max().date().isoformat(),
        "cancelled_invoices": int(cancelled_invoices),
        "cancel_rate": round(cancelled_invoices / total_invoices * 100, 1) if total_invoices else 0,
        "cancelled_value": round(cancelled_value, 2),
        "missing_customer_rows": int(data["customer"].isna().sum()),
    }

    monthly = (
        data.groupby(data["date"].dt.to_period("M"))
        .agg(revenue=("revenue", "sum"), orders=("invoice", "nunique"))
        .reset_index()
    )
    monthly_list = [
        {"month": str(r.date), "revenue": round(float(r.revenue), 2), "orders": int(r.orders)}
        for r in monthly.itertuples()
    ]

    top = (
        data.groupby("description")
        .agg(revenue=("revenue", "sum"), units=("quantity", "sum"))
        .nlargest(10, "revenue")
        .reset_index()
    )
    top_products = [
        {"name": r.description, "revenue": round(float(r.revenue), 2), "units": int(r.units)}
        for r in top.itertuples()
    ]

    countries = []
    if "country" in mapping:
        by_country = data.groupby("country")["revenue"].sum().nlargest(8)
        countries = [{"name": str(k), "revenue": round(float(v), 2)} for k, v in by_country.items()]

    return {
        "cleaning": {"raw_rows": raw_rows, "clean_rows": len(data), "steps": steps},
        "kpis": kpis,
        "monthly": monthly_list,
        "top_products": top_products,
        "top_countries": countries,
        "extras": extra_insights(data),
    }

def extra_insights(data):
    """Business-decision metrics computed from the cleaned rows."""
    out = {}
    total = float(data["revenue"].sum()) or 1.0

    dow = data.groupby(data["date"].dt.dayofweek)["revenue"].sum()
    out["weekday"] = [
        {"label": n, "revenue": round(float(dow.get(i, 0)), 2)}
        for i, n in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    ]
    hr = data.groupby(data["date"].dt.hour)["revenue"].sum()
    out["hourly"] = [{"label": f"{h:02d}", "revenue": round(float(hr.get(h, 0)), 2)} for h in range(24)]
    q = data.groupby(data["date"].dt.quarter)["revenue"].sum()
    out["quarters"] = [{"label": f"Q{i}", "share": round(float(q.get(i, 0)) / total * 100, 1)} for i in range(1, 5)]

    prod = data.groupby("description")["revenue"].sum().sort_values(ascending=False)
    n80 = int(((prod.cumsum() / total) < 0.8).sum()) + 1
    out["pareto"] = {
        "products": int(len(prod)),
        "for_80": n80,
        "pct": round(n80 / len(prod) * 100, 1),
    }
    out["bottom_products"] = [{"name": k, "revenue": round(float(v), 2)} for k, v in prod.tail(5).items()]

    per_order = data.groupby("invoice").agg(
        units=("quantity", "sum"), lines=("stock", "count"), value=("revenue", "sum")
    )
    big = per_order[per_order["value"] >= per_order["value"].quantile(0.9)]
    out["basket"] = {
        "avg_units": round(float(per_order["units"].mean()), 1),
        "avg_lines": round(float(per_order["lines"].mean()), 1),
        "median_value": round(float(per_order["value"].median()), 2),
        "big_orders_share": round(float(big["value"].sum()) / total * 100, 1),
    }

    if data["country"].notna().any():
        by = data.groupby("country")["revenue"].sum().sort_values(ascending=False)
        out["geo"] = {
            "countries": int(len(by)),
            "top": str(by.index[0]),
            "top_share": round(float(by.iloc[0]) / total * 100, 1),
        }

    known = data[data["customer"].notna()]
    if not known.empty:
        ref = known["date"].max() + pd.Timedelta(days=1)
        cust = known.groupby("customer").agg(
            last=("date", "max"), orders=("invoice", "nunique"), revenue=("revenue", "sum")
        )
        cust["recency"] = (ref - cust["last"]).dt.days

        def segment(r):
            if r.recency > 365:
                return "Lost"
            if r.orders >= 2 and r.recency > 180:
                return "At risk"
            if r.orders >= 4 and r.recency <= 90:
                return "Champions"
            if r.orders >= 2:
                return "Loyal"
            if r.recency <= 90:
                return "New"
            return "Occasional"

        cust["segment"] = cust.apply(segment, axis=1)
        seg_total = float(cust["revenue"].sum()) or 1.0
        segs = cust.groupby("segment").agg(count=("orders", "size"), revenue=("revenue", "sum"))
        order = ["Champions", "Loyal", "New", "Occasional", "At risk", "Lost"]
        out["segments"] = [
            {
                "name": s,
                "count": int(segs.loc[s, "count"]),
                "revenue": round(float(segs.loc[s, "revenue"]), 2),
                "share": round(float(segs.loc[s, "revenue"]) / seg_total * 100, 1),
            }
            for s in order if s in segs.index
        ]
        repeat = cust["orders"] > 1
        out["repeat"] = {
            "customers": int(len(cust)),
            "repeat": int(repeat.sum()),
            "rate": round(float(repeat.mean()) * 100, 1),
        }
        top = cust.nlargest(10, "revenue")
        out["top_customers"] = [
            {"id": str(i).split(".")[0], "orders": int(r.orders), "revenue": round(float(r.revenue), 2)}
            for i, r in top.iterrows()
        ]
        out["top10_share"] = round(float(top["revenue"].sum()) / seg_total * 100, 1)
    return out
