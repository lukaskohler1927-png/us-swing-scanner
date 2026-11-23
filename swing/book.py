"""Forward and replay use the same opening, gap, stop/target, and timeout rules."""
from collections import defaultdict
from datetime import date
import math

from .strategy import BORROW, ENTRY_BPS, FEE, HOLD, MAX_NEW, ranked


PORTFOLIO_SLOTS = 9

def choose(plans, occupied=(), recent=(), limit=MAX_NEW):
    blocked = set(occupied) | set(recent)
    selected = []
    has_etf = False
    for p in ranked(plans):
        if len(selected) >= limit:
            break
        if p["symbol"] in blocked or (has_etf and p["asset"] == "ETF"):
            continue
        blocked.add(p["symbol"])
        selected.append(p)
        has_etf |= p["asset"] == "ETF"
    return selected


def advance(position, day, bar):
    """Advance one regular session only. Caller maps every expected session, even missing ones."""
    p = position
    s = p["side"]
    if bar is None or any(not math.isfinite(float(bar[k])) or bar[k] <= 0 for k in ("open","high","low","close")):
        return dict(status="UNKNOWN", end=day)
    op, high, low, close = (float(bar[k]) for k in ("open","high","low","close"))
    if "fill" not in p:
        if not p["lo"] <= op <= p["hi"]:
            return dict(status="EXPIRED", end=day)
        p.update(fill=op, start=day, age=0)
    p["age"] += 1
    p["last"] = close
    stop, target = p["stop"], p["target"]
    adverse, favourable = (low, high) if s == 1 else (high, low)
    if s*(op-stop) <= 0:
        out, status = op, "STOP_GAP"
    elif s*(op-target) >= 0:
        out, status = target, "TARGET"  # no beneficial gap improvement assumed
    elif s*(adverse-stop) <= 0:
        out, status = stop, "STOP"      # stop first if both levels crossed
    elif s*(favourable-target) >= 0:
        out, status = target, "TARGET"
    elif p["age"] >= HOLD:
        out, status = close, "TIME"
    else:
        return None
    days = (date.fromisoformat(day)-date.fromisoformat(p["start"])).days+1
    fee = (p["fill"]+out)*(ENTRY_BPS+FEE)
    borrow = p["fill"]*BORROW*days/365 if s < 0 else 0
    net = s*(out-p["fill"])-fee-borrow
    return dict(status=status, end=day, out=out, net=net,
                realized_r=net/(abs(p["fill"]-stop)+fee+borrow))


def summary(trades):
    closed = [p for p in trades if "net" in p and p.get("qty",1)>0]
    if not closed:
        return dict(n=0, win=None, pf=None, avg_rr=None, avg_r=None, profit=0., loss=0.)
    pnls = [p["net"]*p.get("qty", 1) for p in closed]
    win = sum(x for x in pnls if x > 0)
    loss = -sum(x for x in pnls if x < 0)
    return dict(n=len(closed), win=sum(x > 0 for x in pnls)/len(closed),
                pf=round(win/loss,4) if loss else None,
                avg_rr=sum(p["rr"] for p in closed)/len(closed),
                avg_r=sum(p["realized_r"] for p in closed)/len(closed),
                profit=win, loss=loss)


def replay(index, proposals, by_symbol):
    equity = 100000.
    peak = equity
    dd = 0.
    pending, records, last_signal, active = [], [], {}, {}
    days = list(index)
    for i, d in enumerate(days):
        day = d.date().isoformat()
        for p in pending:
            active[p["symbol"]] = p
        pending = []
        equity_before = equity + sum(p.get("qty",0)*p["side"]*(p.get("last",0)-p.get("fill",0)) for p in active.values())
        # Funding is decided at the open, before this session's exits are known.
        slots = PORTFOLIO_SLOTS - sum(p.get("qty",0)>0 for p in active.values())
        for symbol, p in list(active.items()):
            frame = by_symbol[symbol]
            bar = frame.loc[d] if d in frame.index else None
            outcome = advance(p, day, bar)
            if "fill" in p and "qty" not in p:
                p["qty"] = 0
                if slots > 0:
                    p["qty"] = math.floor(max(0,min(.10*equity_before/p["fill"],
                                             .005*equity_before/abs(p["fill"]-p["stop"]))))
                    if p["qty"] > 0:
                        slots -= 1
            if outcome:
                p.update(outcome)
                if "net" in p:
                    equity += p["net"]*p["qty"]
                elif "qty" in p:
                    # Conservative explicit charge for unobservable exits; count separately.
                    equity -= p["qty"] * abs(p["fill"]-p["stop"])
                records.append(p)
                del active[symbol]
        mark = equity + sum(p["qty"]*p["side"]*(p["last"]-p["fill"]) for p in active.values())
        peak = max(peak, mark)
        dd = max(dd, 1-mark/peak)
        # Purge tail decisions so that no pending entry or exit crosses the partition.
        if i + HOLD < len(days):
            recent = [k for k,v in last_signal.items() if i-v < HOLD]
            pending = [dict(p) for p in choose(proposals.get(day, ()),active,recent)]
            for p in pending:
                last_signal[p["symbol"]] = i
    out = summary(records)
    groups = defaultdict(list)
    for p in records:
        groups[group(p)].append(p)
    out.update(max_drawdown=dd, equity_end=equity, signals=len(records),
               signal_fills=sum("net" in p for p in records),
               unfunded_fills=sum("net" in p and p.get("qty",0)==0 for p in records),
               expired=sum(p["status"]=="EXPIRED" for p in records),
               unknown=sum(p["status"]=="UNKNOWN" for p in records),
               groups={k: summary(v) for k,v in sorted(groups.items())})
    return out


def group(p):
    return f"{p['asset']}|{p['strategy']}|{p['side']}"
