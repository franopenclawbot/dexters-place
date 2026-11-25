#!/usr/bin/env python3
"""DEXTER desk market ticker feed (repo copy for the Pages deploy workflow).

Fetches Yahoo Finance chart-API quotes and writes data/market.json for the
dashboard ticker. The GitHub Actions deploy workflow runs this before
packaging the site, so the Pages copy carries a snapshot as of deploy time.
The LAN copy that refreshes every 2 minutes lives at ~/.hermes/scripts/.

Data rules are copied from the verified pre-market script
(~/.hermes/scripts/techai_premarket_data.py, verified vs CNBC 2026-11-24):
  - synthesize the rolled newest daily bar from meta (Yahoo rolls bars ~20:00 ET);
  - TNX/CL/GC print LEVEL ONLY (session-start date bars make daily % unreliable);
  - ES/NQ are ticks vs the prior CASH close of the reference index;
  - everything else is close-to-close vs the prior session bar.
A symbol that fails collection is written as null and rendered as a dash —
never fabricated.
"""
import json
import sys
import tempfile
import time
import datetime as dt

try:
    import requests

    def http_json(url, timeout=14):
        r = requests.get(url, timeout=timeout, headers=HEADERS)
        return r.status_code, r
except ImportError:  # fall back to stdlib if requests is unavailable
    import urllib.request
    import urllib.error

    def http_json(url, timeout=14):
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            r = urllib.request.urlopen(req, timeout=timeout)
            return 200, _Wrap(r.read())
        except urllib.error.HTTPError as e:
            return e.code, _Wrap(b"")

class _Wrap:
    def __init__(self, body):
        self.text = body.decode("utf-8", "replace")
        self.status_code = 200

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; hermes-research/1.0)"}
ET = dt.timezone(dt.timedelta(hours=-5))  # EST; DST edges handled by labels
OUT = os.environ.get("MARKET_OUT", "data/market.json")
GENERATOR = "dashboard/bin/market_ticker.py"
API = "https://query1.finance.yahoo.com/v8/finance/chart"

# sym, label, kind — kinds: index | equity | cash_future:<ref> | own | level
UNIVERSE = [
    ("^GSPC",   "S&P 500",      "index"),
    ("^IXIC",   "Nasdaq Comp",  "index"),
    ("^DJI",    "Dow",          "index"),
    ("^NDX",    "Nasdaq 100",   "index"),
    ("ES=F",    "ES fut",       "cash_future:^GSPC"),
    ("NQ=F",    "NQ fut",       "cash_future:^NDX"),
    ("^VIX",    "VIX",          "own"),
    ("^TNX",    "10Y yield",    "level"),
    ("DX-Y.NYB","Dollar",       "own"),
    ("CL=F",    "WTI",          "level"),
    ("GC=F",    "Gold",         "level"),
    ("BTC-USD", "BTC",          "own"),
    ("AAPL",    "Apple",        "equity"),
    ("MSFT",    "Microsoft",    "equity"),
    ("NVDA",    "Nvidia",       "equity"),
    ("AMD",     "AMD",          "equity"),
    ("AVGO",    "Broadcom",     "equity"),
    ("GOOGL",   "Alphabet",     "equity"),
    ("META",    "Meta",         "equity"),
    ("AMZN",    "Amazon",       "equity"),
    ("TSLA",    "Tesla",        "equity"),
    ("ORCL",    "Oracle",       "equity"),
    ("MU",      "Micron",       "equity"),
    ("TSM",     "TSMC ADR",     "equity"),
    ("PLTR",    "Palantir",     "equity"),
    ("CRWV",    "CoreWeave",    "equity"),
]

_cache = {}

def fetch(sym, rng="15d", iv="1d", tries=2):
    key = (sym, rng, iv)
    if key in _cache:
        return _cache[key]
    url = f"{API}/{sym}?range={rng}&interval={iv}"
    res = None
    for attempt in range(tries):
        try:
            code, r = http_json(url)
            if code == 200:
                res = json.loads(r.text)["chart"]["result"][0]
                break
            if code == 429:
                time.sleep(1.5)
                continue
            break
        except Exception:
            time.sleep(1.0)
    time.sleep(0.15)
    _cache[key] = res
    return res

def effective_bars(res):
    """[(date, close)] newest last, meta-derived newest session guaranteed."""
    if not res:
        return None, None
    meta = res["meta"]
    ts = res.get("timestamp") or []
    cl = res["indicators"]["quote"][0].get("close") or []
    bars = []
    for t, c in zip(ts, cl):
        if c is not None:
            d = dt.datetime.fromtimestamp(t, ET).date()
            bars.append((d, round(c, 2)))
    if not bars:
        return None, None
    t = meta.get("regularMarketTime")
    price = meta.get("regularMarketPrice")
    if t and price:
        d = dt.datetime.fromtimestamp(t, ET).date()
        if d > bars[-1][0]:
            bars.append((d, round(price, 2)))  # synth rolled session
    return bars, meta

def daily_quote(sym, label, kind):
    res = fetch(sym)
    bars, meta = effective_bars(res)
    if not bars or len(bars) < 2:
        return None
    last = bars[-1][1]
    prev = bars[-2][1]
    price = meta.get("regularMarketPrice") or last
    pct = (price / prev - 1) * 100
    return {
        "sym": sym, "label": label, "kind": kind,
        "price": round(price, 2), "pct": round(pct, 2),
        "basis_note": "close vs prior session",
        "tick_et": None, "bar_date": bars[-1][0].isoformat(),
    }

def live_quote(sym, label, kind, ref_sym=None):
    """Own/cash-basis/level live tick quotes."""
    res = fetch(sym, rng="2d", iv="30m")
    if not res:
        return None
    meta = res["meta"]
    price = meta.get("regularMarketPrice")
    if price is None:
        return None
    tick_et = dt.datetime.fromtimestamp(
        meta.get("regularMarketTime", 0), ET).strftime("%H:%M")
    base = {
        "sym": sym, "label": label, "kind": kind,
        "price": round(price, 2), "pct": None,
        "basis_note": "level only (% unreliable on session-date bars)",
        "tick_et": tick_et, "bar_date": None,
    }
    if kind == "level":
        return base
    ref = ref_sym if ref_sym else sym
    dres = fetch(ref)
    bars, _ = effective_bars(dres)
    if bars and len(bars) >= 2:
        prev_close = bars[-2][1]
        if ref_sym:
            base["pct"] = round((price / prev_close - 1) * 100, 2)
            base["basis_note"] = f"tick vs {ref} prior session close (cash basis, incl. futures basis)"
            base["bar_date"] = bars[-1][0].isoformat()
        else:
            base["pct"] = round((price / prev_close - 1) * 100, 2)
            base["basis_note"] = "tick vs prior session close"
            base["bar_date"] = bars[-1][0].isoformat()
    return base

def market_state(ny_now):
    wd = ny_now.weekday()
    hm = ny_now.hour * 60 + ny_now.minute
    if wd >= 5:
        return {"state": "closed", "note": "weekend"}
    if hm < 570:
        st = "pre"
    elif hm < 960:
        st = "open"
    elif hm < 1200:
        st = "post"
    else:
        st = "closed"
    return {"state": st, "note": "no holiday calendar — treat as approximate"}

def main():
    import os
    now = dt.datetime.now(dt.timezone.utc)
    ny_now = now.astimezone(ET)
    out = {
        "as_of_utc": now.strftime("%Y-%m-%d %H:%M:%SZ"),
        "as_of_et": ny_now.strftime("%Y-%m-%d %H:%M:%S ET"),
        "source": "Yahoo Finance chart API (delayed quotes)",
        "generator": GENERATOR,
        "market_state": market_state(ny_now),
        "quotes": [],
    }
    ok_count = 0
    for sym, label, kind in UNIVERSE:
        try:
            q = None
            if kind in ("index", "equity"):
                q = daily_quote(sym, label, kind)
            elif kind.startswith("cash_future:"):
                q = live_quote(sym, label, "cash_future", ref_sym=kind.split(":", 1)[1])
            else:
                q = live_quote(sym, label, kind)
        except Exception as e:
            print(f"ERR {sym}: {e}", file=sys.stderr)
            q = None
        if q:
            out["quotes"].append(q)
            ok_count += 1
        else:
            out["quotes"].append({"sym": sym, "label": label, "kind": kind,
                                  "price": None, "pct": None,
                                  "basis_note": "data unavailable",
                                  "tick_et": None, "bar_date": None})

    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OUT) or ".", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(out, f, indent=1)
    os.chmod(tmp, 0o644)  # mkstemp defaults to 0600; web server needs read
    os.replace(tmp, OUT)

    fails = len(UNIVERSE) - ok_count
    print(f"ticker wrote {OUT}: {ok_count}/{len(UNIVERSE)} symbols ok, "
          f"as of {out['as_of_et']}")
    if ok_count == 0:
        print("ALL SYMBOLS FAILED", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
