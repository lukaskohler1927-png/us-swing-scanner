"""Fixed chronological split, no optimisation. Offline study and recent feed validation."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import zipfile

import pandas as pd

from .book import replay
from .history import PANEL
from .data import COLS, Reader
from .dolt import Dolt, SOURCE
from .market import bounds, calendar, sessions
from .strategy import VERSION, candidates, clean, features

ARCHIVE_URL = "https://www.kaggle.com/api/v1/datasets/download/camnugent/sandp500"



def fingerprint():
    root = Path(__file__).parent
    return hashlib.sha256(b"".join((root/n).read_bytes() for n in
                   ("strategy.py","book.py","backtest.py","data.py","dolt.py","history.py","market.py","edgar.py","scan.py"))).hexdigest()


def study(frames, first, last, split, source, symbols_requested=None):
    idx = sessions(first,last)
    in_sample, oos = idx[idx < pd.Timestamp(split)], idx[idx >= pd.Timestamp(split)]
    if len(in_sample) < 250 or len(oos) < 60:
        raise ValueError("Zu kurze Testperioden")
    proposals = defaultdict(list)
    cleaned = {}
    bars = 0
    for symbol, df in sorted(frames.items()):
        df = clean(df, idx)
        bars += int(df.close.notna().sum())
        cleaned[symbol] = df
        for p in candidates(symbol, features(df)):
            proposals[p["day"]].append(p)
    return {"engine": VERSION, "fingerprint":fingerprint(), "source":source,
            "generated":datetime.now(timezone.utc).isoformat(), "first":str(idx[0].date()),
            "last":str(idx[-1].date()),"split":split,"symbols":len(frames),
            "requested":symbols_requested or len(frames),"valid_symbol_days":bars,
            "in_sample":replay(in_sample,proposals,cleaned),"oos":replay(oos,proposals,cleaned)}


def archive(path):
    with zipfile.ZipFile(path) as z:
        with z.open("all_stocks_5yr.csv") as f:
            df = pd.read_csv(f,parse_dates=["date"])
    frames = {s:g.set_index("date")[COLS] for s,g in df.groupby("Name")}
    report = study(frames,"2013-02-08","2018-02-07","2016-07-01","Kaggle/camnugent/sandp500")
    report["archive_sha256"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return report


def vendor(now):
    a = Dolt(Reader())
    # Most recent fully settled PRIOR session; never include the current day.
    today = pd.Timestamp(now.date())
    last = calendar().date_to_session(today-pd.Timedelta(days=1),direction="previous").date().isoformat()
    end = bounds(last)[1]
    first = (pd.Timestamp(last)-pd.DateOffset(years=4)).date().isoformat()
    split = (pd.Timestamp(last)-pd.DateOffset(years=1)).date().isoformat()
    a.prepare(PANEL,first,last,panel=True)
    frames = a.bars(PANEL,first,end)
    if len(frames) < .90*len(PANEL):
        raise ValueError("Kursabdeckung im Backtest unter 90 %")
    report = study(frames,first,last,split,SOURCE,len(PANEL))
    report["revision"] = a.ref
    report["history_revision"] = a.base_revision
    if report["valid_symbol_days"] < .85*len(PANEL)*len(sessions(first,last)):
        raise ValueError("Zu viele historische Datenlücken")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive")
    parser.add_argument("--output",required=True)
    args = parser.parse_args()
    report = archive(args.archive) if args.archive else vendor(datetime.now(timezone.utc))
    Path(args.output).write_text(json.dumps(report,indent=2,allow_nan=False),encoding="utf8")
