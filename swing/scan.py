"""Session publication, candidate ranking, historical quotes, and forward ledger."""
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import os

import pandas as pd

from .backtest import fingerprint
from .book import advance, group, summary
from .data import SourceError, universe
from .edgar import Edgar
from .market import bounds, calendar, next_day, sessions
from .strategy import HOLD, MAX_NEW, candidates, clean, event_match, features, ranked
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
    if not (flag("LIVE_ALERTS") and report.get("fingerprint")==fingerprint()
            and report.get("source")=="Alpaca SIP historical"):
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


def full(reader, provider, state, day, now):
    if state["last_scan"] == day:
        return None
    listings, stamps = universe(reader,now,flag("INCLUDE_ETFS"))
    active = {p["symbol"] for p in state["active"]}
    names = sorted(set(listings)|active)
    idx = sessions((pd.Timestamp(day)-pd.Timedelta(days=440)).date(),day)
    _, close = bounds(day)
    # Date-tagged daily bars only, with a delayed historical end parameter.
    cutoff = min(now-timedelta(minutes=20),close+timedelta(hours=4))
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
            if current.close>=5 and len(prev.dropna())==20 and (prev.close*prev.volume).median()>=5e6:
                screened.append(symbol)
    if fresh < .70*len(listings):
        raise SourceError("Unter 70 % aktuelle Abdeckung. Kein neuer Scan veröffentlicht.")
    # Read market news only once. Technical strategies are independent of news availability.
    try:
        news = provider.news(day)
        news_state = "ok"
    except (SourceError, ValueError, KeyError):
        news, news_state = {}, "unavailable"
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
            events = {(day,s):event_match(news.get(symbol,()),s,previous_close,close) for s in (1,-1)}
            last = f.iloc[-1]
            event_side = 1 if last.gap > 0 else -1
            if (sec and sec_reads < 50 and listings[symbol].asset=="Aktie" and abs(last.gap)>.018
                and last.rv>=1.6 and not events[(day,event_side)]
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
    checked, selected, etf_count = {}, [], 0
    for p in ranked(proposals):
        symbol = p["symbol"]
        if symbol in blocked or (p["asset"]=="ETF" and etf_count>=1):
            continue
        if len(selected)>=min(MAX_NEW,9-len(state["active"])):
            break
        if symbol not in checked:
            if len(checked)>=40:
                continue
            checked[symbol] = provider.spread(symbol,day)
        spread = checked[symbol]
        if spread is None or spread>(.0015 if p["side"]==-1 else .002):
            continue
        p.update(name=listings[symbol].name, spread=spread, version=version,
                 key=f"{day}/{symbol}/{p['side']}/{p['strategy']}")
        live = actionable(p,state,now)
        if live or flag("PAPER_TELEGRAM"):
            reserve(state,p["key"],formatted(p,now,not live),expires=bounds(next_day(day))[0].isoformat())
        selected.append(p)
        blocked.add(symbol)
        etf_count += p["asset"]=="ETF"
    state["active"].extend(selected)
    state["days"].append({"day":day,"version":version})
    state["days"] = state["days"][-260:]
    state["last_scan"] = day
    oldest = (date.fromisoformat(day)-timedelta(days=400)).isoformat()
    state["closed"] = [p for p in state["closed"] if p["end"]>=oldest]
    state["outbox"] = [m for m in state["outbox"] if m["key"][:10]>=oldest or m["kind"]=="test"][-2000:]
    return {"session":day,"directory_times":stamps,"listed":len(listings),"fresh":fresh,
            "liquid":len(screened),"with_history":deep_fresh,"technical_ready":ready,"candidate_setups":len(proposals),
            "quotes_checked":len(checked),"selected":len(selected),"etfs_selected":etf_count,
            "news":news_state,"edgar":sec_state,"edgar_lookups":sec_reads,"mode":"paper + eligible opt-in" if flag("LIVE_ALERTS") else "paper",
            "venues":dict(Counter(x.exchange for x in listings.values())),
            "paper_active":len(state["active"]),"paper_resolved":len(state["closed"]),
            "paper_metrics_R_weighted":paper_metrics([p for p in state["closed"] if p.get("version")==version]),
            "unconfirmed_telegram":sum(m["status"] in {"uncertain","reserved"} for m in state["outbox"])}


def opencheck(provider,state,day):
    if state.get("opencheck")==day:
        return None
    plans = [p for p in state["active"] if next_day(p["day"])==day]
    if not plans:
        return None
    opens = provider.opening([p["symbol"] for p in plans],day)
    for p in plans:
        val = opens.get(p["symbol"])
        p["opening_check"] = "unavailable" if val is None else "in_zone" if p["lo"]<=val<=p["hi"] else "outside"
    state["opencheck"] = day
    return {"session":day,"opening_plans":len(plans),"observable":len(opens)}
