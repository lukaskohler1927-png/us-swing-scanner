"""All rolling inputs are trailing. All proposed entries refer to the NEXT open."""
import math
import re

import numpy as np
import pandas as pd

from .data import COLS
from .market import sessions

VERSION = "2026-11-swing-1"
STRATEGIES = ("Momentum Breakout", "Trend Following", "EMA Pullback", "RSI Reversal", "News / Earnings")
SIDE = {1: "LONG", -1: "SHORT"}
ENTRY_BPS = .0010  # one-way execution friction, per dollar
FEE = .0005         # $1 on $2,000 per side, modelling assumption
BORROW = .10        # annualised stress assumption, not an IBKR quote
MAX_NEW = 3
HOLD = 5


def costs(entry, side, days=8):
    return entry * (2 * (ENTRY_BPS + FEE) + (BORROW * days / 365 if side == -1 else 0))


def clean(raw, index):
    """Retain missing sessions as holes and reject inconsistent duplicate bars."""
    if raw.index.has_duplicates:
        raw = raw.rename_axis("session").reset_index().drop_duplicates().set_index("session")
        raw = raw[~raw.index.duplicated(keep=False)]
    df = raw[COLS].apply(pd.to_numeric, errors="coerce").reindex(index)
    valid = (np.isfinite(df).all(axis=1) & (df["low"] > 0) & (df.volume > 0)
             & (df.high >= df[["low", "open", "close"]].max(axis=1))
             & (df.low <= df[["open", "close"]].min(axis=1)))
    return df.where(valid)


def features(df):
    f = df.copy()
    c, h, l, v = f.close, f.high, f.low, f.volume
    # Reset exponential averages after missing bars, including effective split days.
    segments = c.isna().cumsum() if c.isna().any() else None

    def ema(values, **params):
        if segments is None:
            return values.ewm(adjust=False, **params).mean()
        return values.groupby(segments, sort=False).ewm(adjust=False, **params).mean().droplevel(0)

    prev = c.shift()
    f["prev"] = prev
    f["prev_o"] = f.open.shift()
    for length in (20, 50, 200):
        f[f"e{length}"] = ema(c,span=length,min_periods=length)
    f["slope"] = f.e50 - f.e50.shift(5)
    f["macd"] = ema(c,span=12) - ema(c,span=26)
    f["hist"] = f.macd - ema(f.macd,span=9)
    f["last_hist"] = f["hist"].shift()
    tr = pd.concat([(h-l), (h-prev).abs(), (l-prev).abs()], axis=1).max(axis=1)
    f["atr"] = ema(tr,alpha=1/14,min_periods=14)
    delta = c.diff()
    gain = ema(delta.clip(lower=0),alpha=1/14,min_periods=14)
    loss = ema(-delta.clip(upper=0),alpha=1/14,min_periods=14)
    f["rsi"] = (100 * gain / (gain+loss)).fillna(50)
    f["last_rsi"] = f.rsi.shift()
    for n in (3, 20, 60):
        f[f"hi{n}"] = h.shift().rolling(n).max()
        f[f"lo{n}"] = l.shift().rolling(n).min()
    f["rv"] = v / v.shift().rolling(20).median()
    f["dollar"] = (c*v).shift().rolling(20).median()
    f["gap"] = f.open / prev - 1
    # Avoid split-like moves and unstable symbols. A fresh 200-session window is required.
    jump = c.pct_change(fill_method=None).abs()
    f["ready"] = ((c.rolling(200).count() == 200) & (c >= 10) & (f.dollar >= 25e6)
                  & (f.atr/c).between(.007, .075) & (jump.rolling(10).max() <= .30)
                  & (f.gap.abs() <= .18) & (f.rv >= .55))
    return f


def triggers(f, side):
    """Vectorised screening shared by replay and forward runs."""
    s = side
    trend = ((s*(f.e20-f.e50) > 0) & (s*(f.e50-f.e200) > 0)
             & (s*f.slope > 0) & (s*(f.close-f.e20) > 0))
    extreme = f.hi20 if s == 1 else f.lo20
    touch = f.low <= f.e20 + .25*f.atr if s == 1 else f.high >= f.e20 - .25*f.atr
    turn = (f.last_rsi < 32) & (f.rsi >= 32) if s == 1 else (f.last_rsi > 68) & (f.rsi <= 68)
    directional = s*(f.close-f.open) > 0
    masks = {
        STRATEGIES[0]: trend & (s*(f.close-extreme) > 0) & (f.rv >= 1.4) & directional,
        STRATEGIES[1]: trend & (s*f["hist"] > 0) & (s*f.last_hist <= 0) & (f.rv >= .9),
        STRATEGIES[2]: trend & touch & (s*(f.close-f.e20) < f.atr) & directional
                       & (s*(f.prev-f.prev_o) < 0) & (f.rv >= .85),
        STRATEGIES[3]: turn & directional & (s*(f.close-f.prev) > 0) & (f.rv >= 1.1),
        STRATEGIES[4]: (s*f.gap > .018) & directional & (f.rv >= 1.6) & (s*(f.close-f.prev) > f.atr),
    }
    short_ok = (f.dollar >= 50e6) & (f.rv < 6) & (f.gap.abs() < .085) & (f.atr/f.close < .055)
    ready = f.ready & (short_ok if s == -1 else True)
    return {k: v & ready for k, v in masks.items()}


POS = re.compile(r"beats? (?:estimates|expectations|consensus)|beats? (?:Q[1-4] )?(?:EPS|earnings|sales)|rais(?:es|ed) (?:its |full.year |FY\w* )?(?:guidance|outlook)|FDA approv(?:es|al)|contract award", re.I)
NEG = re.compile(r"miss(?:es|ed) (?:estimates|expectations|consensus|(?:Q[1-4] )?(?:EPS|earnings|sales))|(?:cuts?|lowers?|withdraws?) (?:its |full.year |FY\w* )?(?:guidance|outlook)|FDA reject|clinical (?:trial )?hold", re.I)


def event_match(stories, side, previous_close, current_close):
    for t, headline, url in stories:
        if not previous_close < t <= current_close:
            continue
        pos, neg = POS.search(headline), NEG.search(headline)
        hit = pos if side == 1 else neg
        if hit and not (pos and neg) and not re.search(r"\b(may|might|could|unlikely|expected to|not|preview|if)\b", headline, re.I):
            return {"keyword": hit.group(), "at": t.isoformat(),
                    "url": url if url.startswith("https://") else ""}
    return None


def proposal(r, strategy, side, asset="Aktie", event=None):
    if strategy == STRATEGIES[4] and (not event or asset == "ETF"):
        return None
    s = side
    entry = round(float(r.close), 2)
    atr = float(r.atr)
    lo, hi = round(entry-.12*atr, 2), round(entry+.12*atr, 2)
    worst = hi if s == 1 else lo
    pivot = r.lo3 if s == 1 else r.hi3
    stop = round(min(pivot-.10*atr, entry-.95*atr) if s == 1
                 else max(pivot+.10*atr, entry+.95*atr), 2)
    risk = s*(worst-stop)
    if not .8*atr <= risk <= 2.8*atr:
        return None
    # 20-day measured range capped at 4.8 ATR; nearer 60-day barrier caps the target.
    projection = min(4.8*atr, .85*(r.hi20-r.lo20))
    barrier = r.hi60 if s == 1 else r.lo60
    if s*(barrier-entry) > .15*atr:
        projection = min(projection, s*(barrier-entry)-.1*atr)
    target = round(entry+s*projection, 2)
    friction = costs(worst, s)
    rr = (s*(target-worst)-friction)/(risk+friction)
    if min(stop, target, lo) <= 0 or rr < 2:
        return None
    # 50 points for the hard strategy trigger, plus four published quality components.
    volume = min(15, max(0, round(10*(r.rv-.5))))
    liquidity = min(10, max(0, round(5*math.log10(max(1,r.dollar/1e6)))))
    reward = min(15, max(0, round(5*rr)))
    if strategy == STRATEGIES[3]:
        confirm = s*(r.rsi-r.last_rsi) >= 4
    else:
        confirm = s*r["hist"] > 0 and s*r.slope > 0
    score = 50 + volume + liquidity + reward + (10 if confirm else 0)
    if score < 75:
        return None
    reasons = {
        STRATEGIES[0]: f"20-Tage-{'Hoch überschritten' if s==1 else 'Tief unterschritten'}, EMAs in Trendrichtung.",
        STRATEGIES[1]: "MACD-Histogramm wechselt in Richtung des EMA-Trends.",
        STRATEGIES[2]: "EMA 20 getestet, Schlusskurs zurück auf der Trendseite.",
        STRATEGIES[3]: f"RSI dreht von {r.last_rsi:.1f} auf {r.rsi:.1f}, Tageskerze bestätigt.",
        STRATEGIES[4]: f"Kurslücke {r.gap:+.1%}, Nachricht und Tagesbewegung stimmen überein.",
    }
    reason = reasons[strategy] + f" Relatives Volumen {r.rv:.2f}×, ATR {atr:.2f} USD."
    if event:
        reason += f" Meldung: {event['keyword']} ({event['at']})."
    return dict(strategy=strategy, side=s, asset=asset, entry=entry, lo=lo, hi=hi, stop=stop,
                target=target, score=int(score), rr=round(rr, 3), reason=reason,
                components=[50, int(volume), int(liquidity), int(reward), 10 if confirm else 0],
                event=event)


def candidates(symbol, f, asset="Aktie", last_only=False, events=None):
    rows = []
    for side in (1, -1):
        for name, mask in triggers(f, side).items():
            if last_only:
                mask = mask.iloc[-1:]
            if name == STRATEGIES[4] and not events:
                continue
            for day in mask.index[mask]:
                event = (events or {}).get((day.date().isoformat(), side)) if name == STRATEGIES[4] else None
                p = proposal(f.loc[day], name, side, asset, event)
                if p:
                    rows.append(dict(p, symbol=symbol, day=day.date().isoformat()))
    return rows


def ranked(rows):
    return sorted(rows, key=lambda p: (-p["score"], -p["rr"], p["symbol"], p["strategy"], -p["side"]))
