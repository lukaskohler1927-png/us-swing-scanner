"""Entry points for GitHub Actions and isolated local replay."""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys

from . import store
from .backtest import fingerprint, vendor
from .data import Alpaca, Reader, universe
from .market import NY, run_day
from .scan import full, opencheck
from .telegram import dispatch, pair, reserve


def clock():
    return datetime.now(timezone.utc)


def publish_status(output):
    line = json.dumps(output, ensure_ascii=False,allow_nan=False)
    print(line,flush=True)
    if "GITHUB_STEP_SUMMARY" in os.environ:
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a") as f:
            f.write("### US Swing Scanner\n\n```json\n"+json.dumps(output,indent=2,ensure_ascii=False)+"\n```\n")


def run(action):
    now = clock()
    reader = Reader()
    if action=="health":
        names, stamps = universe(reader,now)
        publish_status({"listings":len(names),"venues":dict(Counter(x.exchange for x in names.values())),
                        "directory_times":stamps})
        return
    day = run_day(now,action) if action in {"scan","opencheck"} else None
    if action in {"scan","opencheck"} and day is None:
        publish_status({"status":"ausserhalb des vorgesehenen Handelsfensters","mode":action})
        return
    state = store.read()
    if action=="pair-test":
        pair(state,now)
        reserve(state,"test/"+now.date().isoformat(),
                "Verbindungstest erfolgreich. Der Scanner ist mit diesem privaten Chat gekoppelt. Dies ist ein technischer Test.","test")
        store.save(state)
        dispatch(state,store.save,clock)
        publish_status({"status":"gekoppelt","test":state["outbox"][-1]["status"]})
        return
    if action=="backtest":
        report = vendor(now)
        state["validation"] = report
        store.save(state)
        publish_status({"validation_source":report["source"],"last":report["last"],"oos":report["oos"]})
        return
    provider = Alpaca(reader)
    if action=="opencheck":
        report = opencheck(provider,state,day)
        if report:
            store.save(state)
            publish_status(report)
        return
    old = state.get("validation") or {}
    # Refresh on first complete scan and every 30 days, even after a missed scheduled run.
    stale = (old.get("fingerprint")!=fingerprint() or
             (now.date()-datetime.fromisoformat(old["last"]).date()).days>30)
    if stale:
        state["validation"] = vendor(now)
        store.save(state)
    report = full(reader,provider,state,day,now)
    if report:
        store.save(state,report)
        publish_status(report)
    else:
        publish_status({"session":day,"status":"bereits veröffentlicht"})
    dispatch(state,store.save,clock)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action",choices=["health","pair-test","backtest","opencheck","scan"])
    args = p.parse_args()
    try:
        run(args.action)
    except Exception as e:
        # Do not echo provider URLs, request bodies, tokens, or chat IDs.
        safe = (str(e) if type(e).__module__ in {"swing.data","swing.telegram"} else type(e).__name__)
        publish_status({"status":"fehlgeschlagen","action":args.action,"error":safe})
        raise SystemExit(1) from None


if __name__=="__main__":
    main()
