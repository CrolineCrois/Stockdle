"""Live intraday prices and headlines via yfinance.

Prices come from ``Ticker.history(period="1mo", interval="5m")`` (Yahoo only
keeps a short intraday window). Headlines come from ``Ticker.news`` and are
aligned to the price series by publish timestamp: the index of the last bar at
or before the headline is recorded as the event index, so the round builder can
cut the window exactly at the news.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .common import load_with_fallback, log
from .seed_gen import TICKERS

INTERVAL = "5m"
PERIOD = "1mo"


def _news_items(tk) -> list[dict]:
    """Normalise yfinance's news payload, which has changed shape over versions."""
    try:
        raw = tk.news or []
    except Exception:  # noqa: BLE001
        return []
    out = []
    for item in raw:
        content = item.get("content") if isinstance(item, dict) else None
        if isinstance(content, dict):                        # newer yfinance
            title = content.get("title")
            pub = content.get("pubDate") or content.get("displayTime")
            publisher = (content.get("provider") or {}).get("displayName")
            stamp = None
            if isinstance(pub, str):
                try:
                    stamp = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                except ValueError:
                    stamp = None
        else:                                                # older yfinance
            title = item.get("title")
            epoch = item.get("providerPublishTime")
            publisher = item.get("publisher")
            stamp = (datetime.fromtimestamp(epoch, tz=timezone.utc)
                     if isinstance(epoch, (int, float)) else None)
        if title and stamp:
            out.append({"title": str(title).strip(),
                        "published": stamp.astimezone(timezone.utc),
                        "publisher": publisher or "Yahoo Finance"})
    return out


def fetch_live() -> list[dict]:
    import yfinance as yf  # imported lazily so the module loads without it

    series = []
    for spec in TICKERS:
        symbol = spec["t"]
        tk = yf.Ticker(symbol)
        hist = tk.history(period=PERIOD, interval=INTERVAL, auto_adjust=False)
        if hist is None or hist.empty or len(hist) < 400:
            log(f"stock: {symbol} returned {0 if hist is None else len(hist)} bars, skipping")
            continue
        hist = hist.dropna(subset=["Close"])
        stamps = [ts.to_pydatetime().astimezone(timezone.utc) for ts in hist.index]
        y = [float(v) for v in hist["Close"].tolist()]

        events = []
        for item in _news_items(tk):
            # Last bar at or before publish time.
            at = None
            for i, s in enumerate(stamps):
                if s <= item["published"]:
                    at = i
                else:
                    break
            # Need room for the visible run-up and the 50 hidden points.
            if at is None or at < 80 or at > len(y) - 60:
                continue
            events.append({
                "idx": at,
                "title": item["title"],
                "published": item["published"].isoformat(),
                "publisher": item["publisher"],
            })

        series.append({
            "source": "stock",
            "key": symbol,
            "unit": "$",
            "y_label": "Price ($)",
            "x_label": f"Bars ({INTERVAL})",
            "freq": INTERVAL,
            "is_seed": False,
            "t": [s.isoformat() for s in stamps],
            "y": [round(v, 4) for v in y],
            "aux": {},
            "meta": {"ticker": symbol, "name": spec["name"],
                     "source_note": f"yfinance {PERIOD}/{INTERVAL} close"},
            "events": sorted(events, key=lambda e: e["idx"]),
        })
        log(f"stock: {symbol} live {len(y)} bars, {len(events)} aligned headlines")

    if len(series) < 3:
        raise RuntimeError(f"only {len(series)} tickers usable from yfinance")
    return series


def load(use_live: bool = True) -> list[dict]:
    return load_with_fallback("stock", fetch_live, use_live=use_live,
                              max_cache_hours=6.0)


if __name__ == "__main__":
    for s in load():
        print(s["key"], len(s["y"]), len(s["events"]), "seed" if s["is_seed"] else "live")
