"""Deterministic market-data verification snapshot.

The market analyst is an LLM that can confabulate exact numbers — citing a
Bollinger band or a "historically validated bounce" that the underlying data
doesn't support (#830). This module computes a ground-truth snapshot (latest
OHLCV row on or before the analysis date, common indicators, recent closes)
the analyst is told to treat as the source of truth for any exact numeric
claim. Deterministic, no LLM involved.
"""

from __future__ import annotations

from collections.abc import Iterable
from io import StringIO

import pandas as pd
from stockstats import wrap

from tradingagents.dataflows.interface import route_to_vendor

# A fixed, common indicator set so the snapshot is the same shape every run.
DEFAULT_SNAPSHOT_INDICATORS: tuple[str, ...] = (
    "close_10_ema", "close_50_sma", "close_200_sma",
    "rsi", "boll", "boll_ub", "boll_lb",
    "macd", "macds", "macdh", "atr",
)


def _parse_routed_ohlcv_csv(raw: str) -> pd.DataFrame:
    """Convert routed stock-data CSV output into stockstats-compatible OHLCV."""
    text = (raw or "").strip()
    if not text or text.startswith(("NO_DATA_AVAILABLE:", "DATA_UNAVAILABLE:")):
        raise ValueError(text or "No OHLCV data returned by vendor router.")

    data = pd.read_csv(StringIO(text), comment="#")
    if data.empty:
        raise ValueError("No OHLCV rows returned by vendor router.")

    column_map = {}
    for column in data.columns:
        key = str(column).strip().lower().replace(" ", "_")
        if key in {"date", "datetime", "timestamp"}:
            column_map[column] = "Date"
        elif key == "open":
            column_map[column] = "Open"
        elif key == "high":
            column_map[column] = "High"
        elif key == "low":
            column_map[column] = "Low"
        elif key in {"close", "adjusted_close"}:
            column_map[column] = "Close"
        elif key == "volume":
            column_map[column] = "Volume"

    data = data.rename(columns=column_map)
    missing = {"Date", "Close"} - set(data.columns)
    if missing:
        raise ValueError(
            "Routed stock data missing required OHLCV column(s): "
            + ", ".join(sorted(missing))
        )
    return data


def load_verified_ohlcv(symbol: str, curr_date: str) -> pd.DataFrame:
    """Load OHLCV through the configured vendor chain for verification snapshots."""
    end = pd.to_datetime(curr_date).strftime("%Y-%m-%d")
    start = (pd.to_datetime(curr_date) - pd.DateOffset(years=5)).strftime("%Y-%m-%d")
    routed = route_to_vendor("get_stock_data", symbol, start, end)
    return _parse_routed_ohlcv_csv(routed)


def _verified_rows(symbol: str, curr_date: str) -> pd.DataFrame:
    """OHLCV on or before curr_date, date-sorted. Raises if nothing usable.

    ``load_verified_ohlcv`` already normalizes routed vendor output, but we
    re-apply the cutoff defensively because this verification path must not
    trust its input to be pre-filtered.
    """
    data = load_verified_ohlcv(symbol, curr_date)
    if data is None or data.empty:
        raise ValueError(f"No OHLCV data available for {symbol}.")

    df = data.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"])
    df = df[df["Date"] <= pd.to_datetime(curr_date)].sort_values("Date")
    if df.empty:
        raise ValueError(f"No OHLCV rows on or before {curr_date} for {symbol}.")
    return df


def _fmt(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def build_verified_market_snapshot(
    symbol: str,
    curr_date: str,
    look_back_days: int = 30,
    indicators: Iterable[str] | None = None,
) -> str:
    """Render a ground-truth snapshot: latest OHLCV row, indicators, recent closes."""
    # `df` keeps the original capitalized OHLCV columns (Open/High/Low/Close/
    # Volume); stockstats `wrap()` lowercases columns and adds indicator
    # columns, so read raw prices from `df` and indicators from `stock_df`.
    df = _verified_rows(symbol, curr_date)
    stock_df = wrap(df.copy())

    selected = tuple(indicators or DEFAULT_SNAPSHOT_INDICATORS)
    indicator_values: dict[str, str] = {}
    for name in selected:
        try:
            stock_df[name]  # triggers stockstats calculation
            indicator_values[name] = _fmt(stock_df.iloc[-1][name])
        except Exception as exc:  # noqa: BLE001 — one bad indicator shouldn't sink the snapshot
            indicator_values[name] = f"N/A ({type(exc).__name__})"

    latest = df.iloc[-1]
    latest_date = _fmt(latest["Date"])
    window = max(1, min(int(look_back_days), 30))
    recent = df.tail(window)

    lines = [
        f"## Verified market data snapshot for {symbol.upper()}",
        "",
        f"- Requested analysis date: {curr_date}",
        f"- Latest trading row used: {latest_date}",
        "- Rows after the requested analysis date are excluded before verification.",
        "",
        "### Latest verified OHLCV row",
        "",
        "| Field | Value |",
        "|---|---:|",
    ]
    for field in ("Open", "High", "Low", "Close", "Volume"):
        lines.append(f"| {field} | {_fmt(latest.get(field))} |")

    lines += ["", "### Verified technical indicators (latest row)", "",
              "| Indicator | Value |", "|---|---:|"]
    for name, value in indicator_values.items():
        lines.append(f"| {name} | {value} |")

    lines += ["", f"### Recent verified closes (last {len(recent)} rows)", "",
              "| Date | Close |", "|---|---:|"]
    for _, row in recent.iterrows():
        lines.append(f"| {_fmt(row['Date'])} | {_fmt(row.get('Close'))} |")

    lines += [
        "",
        "Use this snapshot as the source of truth for exact OHLCV, price-level, "
        "and indicator-value claims. If another tool output conflicts with it, "
        "flag the discrepancy rather than inventing a reconciled number. Do not "
        "claim historical validation, support/resistance bounces, or exact "
        "percentage moves unless directly supported by tool output with concrete "
        "dates and prices.",
    ]
    return "\n".join(lines)
