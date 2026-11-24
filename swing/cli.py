"""Run the scheduled scan, delivery pairing and reproducible verification jobs."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os

import pandas as pd

from . import store
from .backtest import fingerprint, vendor
from .data import Reader, universe, SourceError
from .dolt import Dolt
from .market import NY, bounds, calendar, run_day
from .scan import full, needs_scan
from .telegram import dispatch, pair, reserve


def clock():
    return datetime.now(timezone.utc)


def publish_status(output):
    print(json.dumps(output, ensure_ascii=False, allow_nan=False), flush=True)
    if "GITHUB_STEP_SUMMARY" in os.environ:
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write("### US Swing Scanner\n\n```json\n"+json.dumps(output,indent=2,ensure_ascii=False)+"\n```\n")


def run(action):
    now = clock()
    reader = Reader()
    if action == "pair-test":
        state = store.read()
        pair(state,now)
        run_id = os.getenv("GITHUB_RUN_ID") or now.isoformat()
        attempt = os.getenv("GITHUB_RUN_ATTEMPT","1")
        key = f"test/{run_id}/{attempt}"
        reserve(state,key,
                "Verbindungstest erfolgreich. Du erhältst hier qualifizierte Paper-Signale.", "test")
        store.save(state)
        dispatch(state,store.save,clock)
        test = next(m for m in state["outbox"] if m["key"] == key)
        publish_status({"status":"gekoppelt","test":test["status"]})
        return
    if action == "health":
        names, stamps = universe(reader,now)
        provider = Dolt(reader)
        provider.prepare(["AAPL"],provider.latest,provider.latest,panel=True)
        sample = provider.frames.get("AAPL")
        if sample is None or sample.empty or pd.isna(sample.close.iloc[-1]):
            raise SourceError("Tageskurs-Stichprobe fehlt")
        publish_status({"listings":len(names),"venues":dict(Counter(x.exchange for x in names.values())),
                        "directory_times":stamps,"price_session":provider.latest,"revision":provider.ref,
                        "sample":{"symbol":"AAPL","close":float(sample.close.iloc[-1]),"currency":"USD"}})
        return
    persistent = bool(os.getenv("STATE_KEY") or os.getenv("TELEGRAM_BOT_TOKEN"))
    if action == "verify":
        today = now.astimezone(NY).date()
        session = calendar().date_to_session(pd.Timestamp(today),direction="previous")
        if bounds(session)[1] > now:
            session = calendar().previous_session(session)
        day = session.date().isoformat()
        publish_status(full(reader,Dolt(reader),store.blank(),day,now))
        return
    state = store.read() if persistent else store.blank()
    if action == "backtest":
        report = vendor(now)
        if persistent:
            state["validation"] = report
            store.save(state)
        publish_status(report)
        return
    day = run_day(now,action)
    if day is None:
        publish_status({"status":"Kein gültiges Einstiegsfenster. Neue Tagesideen sind ab 45 Minuten nach US-Schluss bis zur nächsten regulären Eröffnung möglich.","mode":action})
        return
    if not needs_scan(state,day,now):
        publish_status({"session":day,"status":"Für diese Sitzung bereits gescannt. Bestehende Ideen werden nur einmal gesendet."})
    else:
        provider = Dolt(reader)
        if provider.latest < day:
            # Further scheduled attempts will recheck the source before the next open.
            # Keep this session unprocessed so a later run can publish its actual bars.
            if os.getenv("PRICE_RETRY_PLANNED", "").lower() == "true":
                publish_status({"status":"Wartet auf Schlusskurse. Weiterer automatischer Versuch geplant.",
                                "erwartete_sitzung":day,"letzte_quellsitzung":provider.latest})
                return
            raise SourceError(f"Tageskurse für {day} fehlen. Letzte Sitzung der Quelle: {provider.latest}")
        old = state.get("validation") or {}
        if persistent and (old.get("fingerprint") != fingerprint() or
                           (now.date()-datetime.fromisoformat(old["last"]).date()).days > 30):
            state["validation"] = vendor(now)
            store.save(state)
        report = full(reader,provider,state,day,now)
        if persistent:
            store.save(state,report)
        publish_status({**report,"journal_persistent":persistent,"telegram_paired":bool(state["chat"])})
    if persistent:
        dispatch(state,store.save,clock)
        signals = [m for m in state["outbox"] if m["kind"]=="signal" and m["key"].startswith(day+"/")]
        publish_status({"session":day,"telegram_signals":dict(Counter(m["status"] for m in signals))})


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action",choices=["jetzt-scannen","health","pair-test","backtest","verify","catchup","scan"])
    args = p.parse_args()
    try:
        run(args.action)
    except Exception as e:
        safe = str(e) if isinstance(e,SourceError) or type(e).__module__=="swing.telegram" else type(e).__name__
        publish_status({"status":"fehlgeschlagen","action":args.action,"error":safe})
        raise SystemExit(1) from None


if __name__=="__main__":
    main()
