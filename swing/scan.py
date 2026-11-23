"""Session publication, candidate ranking, historical quotes, and forward ledger."""
from collections import Counter
from datetime import date, timedelta
import os

import pandas as pd

from .backtest import fingerprint
from .book import advance, choose, group
from .data import SourceError, universe
from .dolt import SOURCE
from .edgar import Edgar
from .market import bounds, calendar, next_day, sessions
from .strategy import HOLD, MAX_NEW, candidates, clean, features
from .telegram import formatted, reserve


def flag(key):
    return os.getenv(key,"").lower()=="true"


def acceptable(metric, n):
    return metric.get("n",0)>=n and (metric.get("pf") or 0)>=1.10 and (metric.get("avg_r") or 0)>0


def paper_metrics(records):
    closed = [p for p in records if "realized_r" in p]
    positive = sum(max(0,p["realized_r"]) for p in closed)
    losses = -sum(min(0,p["realized_r"]) for p in closed)
    return {"n":len(closed),"pf":round(positive/losses,4) if losses else None,
            "win":round(sum(p["realized_r"]>0 for p in closed)/len(closed),4) if closed else None,
            "avg_r":round(sum(p["realized_r"] for p in closed)/len(closed),4) if closed else None}


def actionable(p, state, now):
    report = state.get("validation") or {}
    if not (p.get("spread") is not None and flag("LIVE_ALERTS") and report.get("fingerprint")==fingerprint()
            and report.get("source")==SOURCE):
        return False
    age = (now.date()-date.fromisoformat(report["last"])).days
    code = p["version"]
    days = [v for v in state["days"] if v["version"]==code]
    forward = [v for v in state["closed"] if v.get("version")==code and v.get("status")!="UNKNOWN"]
    oos = report["oos"]
    return (0<=age<=45 and len(days)>=20 and oos["unknown"]==0
            and acceptable(oos,30) and acceptable(oos["groups"].get(group(p),{}),30)
            and acceptable(paper_metrics([v for v in forward if group(p)==group(v)]),20))


def reconcile(state, frames, day, version):
    living = []
    for p in state["active"]:
        frame = frames.get(p["symbol"])
        checked = p.get("checked",p["day"])
        if checked >= day:
            living.append(p)
            continue
        outcome = None
        anchor = pd.Timestamp(checked)
        # Split corrections change the units of published prices. Do not score a false gain/loss.
        if (frame is None or anchor not in frame.index or pd.isna(frame.loc[anchor,"close"])
            or abs(frame.loc[anchor,"close"]/p.get("last",p["entry"])-1) > .015):
            outcome = dict(status="UNKNOWN",end=day)
        else:
            for d in sessions(next_day(checked),day):
                row = frame.loc[d] if d in frame.index else None
                outcome = advance(p,d.date().isoformat(),row)
                p["checked"] = d.date().isoformat()
                if outcome:
                    break
        if outcome:
            p.update(outcome)
            state["closed"].append(p)
            initial = next((m for m in state["outbox"] if m["key"]==p["key"]),{})
            if p["status"] in {"EXPIRED","UNKNOWN"} and initial.get("status")=="sent":
                reason = "Eröffnung ausserhalb des Einstiegsbereichs." if p["status"]=="EXPIRED" else "Kursreihe fehlt oder wurde korrigiert."
                reserve(state,p["key"]+"/invalid",f"UNGÜLTIG – {p['symbol']} · Idee vom {p['day']}\n{reason}","invalidation")
        else:
            living.append(p)
    state["active"]=living


def needs_scan(state, day, now):
    last = state["last_scan"]
    if not last or last < day:
        return True
    # Old journals used a three-signal cap and had no limit field.
    return (last == day and state.get("last_scan_limit",3) < MAX_NEW
            and now < bounds(next_day(day))[0])


def full(reader, provider, state, day, now):
    if not needs_scan(state,day,now):
        return None
    listings, stamps = universe(reader,now,flag("INCLUDE_ETFS"))
    active = {p["symbol"] for p in state["active"]}
    names = sorted(set(listings)|active)
    idx = sessions((pd.Timestamp(day)-pd.Timedelta(days=440)).date(),day)
    _, close = bounds(day)
    # Date-tagged daily bars only, with a delayed historical end parameter.
    cutoff = min(now-timedelta(minutes=20),close+timedelta(hours=4))
    provider.prepare(names,str(idx[0].date()),day)
    short_idx = idx[-23:]
    screened, track = [], {}
    fresh = 0
    for i in range(0,len(names),120):
        batch = names[i:i+120]
        frames = provider.bars(batch,str(short_idx[0].date()),cutoff)
        for symbol,raw in frames.items():
            df = clean(raw,short_idx)
            current = df.iloc[-1]
            if symbol in active:
                track[symbol] = df
            if symbol not in listings or pd.isna(current.close):
                continue
            fresh += 1
            prev = df.iloc[-21:-1]
            if current.close>=10 and len(prev.dropna())==20 and (prev.close*prev.volume).median()>=25e6:
                screened.append(symbol)
    if fresh < .70*len(listings):
        raise SourceError("Unter 70 % aktuelle Abdeckung. Kein neuer Scan veröffentlicht.")
    sec, sec_reads = None, 0
    sec_state = "disabled"
    if os.getenv("SEC_USER_AGENT"):
        try:
            sec = Edgar(reader)
            sec_state = "ok"
        except (SourceError, KeyError, ValueError):
            sec_state = "unavailable"
    previous = calendar().previous_session(pd.Timestamp(day)).date().isoformat()
    previous_close = bounds(previous)[1]
    proposals = []
    ready = 0
    deep_fresh = 0
    for i in range(0,len(screened),32):
        frames = provider.bars(screened[i:i+32],str(idx[0].date()),cutoff)
        for symbol,raw in frames.items():
            df = clean(raw,idx)
            if symbol in active:
                track[symbol] = df
            deep_fresh += int(pd.notna(df.close.iloc[-1]))
            f = features(df)
            if not bool(f.ready.iloc[-1]):
                continue
            ready += 1
            events = {}
            last = f.iloc[-1]
            event_side = 1 if last.gap > 0 else -1
            if (sec and sec_reads < 50 and listings[symbol].asset=="Aktie" and abs(last.gap)>.018
                and last.rv>=1.6
                and event_side*(last.close-last.prev)>last.atr):
                sec_reads += 1
                try:
                    events[(day,event_side)] = sec.earnings(symbol,previous_close,close)
                except (SourceError, ValueError, KeyError):
                    sec, sec_state = None, "unavailable"
            proposals.extend(candidates(symbol,f,listings[symbol].asset,True,events))
    # Missing long-lookback answers on an otherwise liquid panel must not look like a complete scan.
    if screened and deep_fresh < .95*len(screened):
        raise SourceError("Unvollständige Langzeitabfrage. Keine Veröffentlichung.")
    version = fingerprint()
    reconcile(state,track,day,version)
    blocked = {p["symbol"] for p in state["active"]}
    recent = set(str(t.date()) for t in idx[-(HOLD-1):])
    blocked.update(p["symbol"] for p in state["closed"] if p["day"] in recent)
    previous = [p for p in state["active"] + state["closed"] if p["day"] == day]
    if any(p["asset"] == "ETF" for p in previous):
        proposals = [p for p in proposals if p["asset"] != "ETF"]
    selected = choose(proposals,blocked,limit=max(0,MAX_NEW-len(previous)))
    for p in selected:
        symbol = p["symbol"]
        p.update(name=listings[symbol].name, spread=None, version=version,
                 key=f"{day}/{symbol}/{p['side']}/{p['strategy']}")
        live = actionable(p,state,now)
        if live or os.getenv("PAPER_TELEGRAM","").lower() != "false":
            reserve(state,p["key"],formatted(p,now,not live),expires=bounds(next_day(day))[0].isoformat())
    state["active"].extend(selected)
    if state["last_scan"] != day:
        state["days"].append({"day":day,"version":version})
    state["last_scan_limit"] = MAX_NEW
    daily = previous + selected
    state["days"] = state["days"][-260:]
    state["last_scan"] = day
    oldest = (date.fromisoformat(day)-timedelta(days=400)).isoformat()
    state["closed"] = [p for p in state["closed"] if p["end"]>=oldest]
    state["outbox"] = [m for m in state["outbox"] if m["key"][:10]>=oldest or m["kind"]=="test"][-2000:]
    return {"session":day,"directory_times":stamps,"listed":len(listings),"fresh":fresh,
            "liquid":len(screened),"with_history":deep_fresh,"technical_ready":ready,"candidate_setups":len(proposals),
            "quotes_checked":0,"revision":provider.ref,"history_revision":provider.base_revision,"price_source":SOURCE,"selected":len(daily),"new_this_run":len(selected),
            "daily_limit":MAX_NEW,"selected_long":sum(p["side"]==1 for p in daily),
            "selected_short":sum(p["side"]==-1 for p in daily),"etfs_selected":sum(p["asset"]=="ETF" for p in daily),
            "news":"SEC earnings only","edgar":sec_state,"edgar_lookups":sec_reads,"mode":"paper",
            "venues":dict(Counter(x.exchange for x in listings.values())),
            "paper_active":len(state["active"]),"paper_resolved":len(state["closed"]),
            "paper_metrics_R_weighted":paper_metrics([p for p in state["closed"] if p.get("version")==version]),
            "unconfirmed_telegram":sum(m["status"] in {"uncertain","reserved"} for m in state["outbox"])}
