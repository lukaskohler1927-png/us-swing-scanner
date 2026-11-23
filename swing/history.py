"""Compact weekly baseline made from the publisher's public CSV table export."""
import csv
from datetime import date, timedelta
import gzip
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

import pandas as pd

from .data import COLS, SourceError

EXPORT = "https://www.dolthub.com/csv/post-no-preference/stocks/master/"
FIELDS = ["date", "act_symbol", *COLS]
ROOT = Path(".cache/public-prices")
PANEL = """AAPL ABBV ABT ACN ADBE ADI ADP AIG AMAT AMD AMGN AMZN AXP BA BAC BK BLK BMY BSX C CAT CL CMCSA COP COST CRM CSCO CVS CVX DE DHR DIS DUK EMR F FDX GD GE GILD GM GOOGL GS HD HON IBM INTC JNJ JPM KO LLY LMT LOW MA MCD MDT MET MMM MO MRK MS MSFT NEE NKE NVDA ORCL PEP PFE PG QCOM RTX SBUX SO T TGT TMO TXN UNH UNP UPS USB V VZ WFC WMT XOM""".split()


def download(table, path):
    # curl streams the complete export to runner scratch; retry starts a fresh file.
    if table not in {"ohlcv","split"}:
        raise ValueError("Unbekannte Tabelle")
    cmd = ["curl","--fail","--silent","--show-error","--location","--compressed",
           "--connect-timeout","20","--max-time","1000","--retry","1","--retry-max-time","1100",
           "--output",str(path),EXPORT+table]
    if subprocess.run(cmd,check=False).returncode:
        raise SourceError("CSV-Export von DoltHub nicht vollständig abrufbar")


def compact(src, dst, latest, expected):
    end = date.fromisoformat(latest)
    market_start = (end-timedelta(days=460)).isoformat().encode()
    panel_start = (end-timedelta(days=1500)).isoformat().encode()
    panel = {s.encode() for s in PANEL}
    stamp = latest.encode()
    seen = 0
    with open(src,"rb") as inp, gzip.open(dst,"wb",compresslevel=3) as out:
        header = inp.readline().strip()
        if header != ",".join(FIELDS).encode():
            raise SourceError("Unerwarteter OHLCV-Export")
        out.write(header+b"\n")
        for line in inp:
            d = line[:10]
            if d < panel_start:
                continue
            if d > stamp or not line.endswith(b"\n") or line[10:11]!=b",":
                raise SourceError("Kurs-Export unvollständig oder inzwischen geändert")
            if d == stamp:
                seen += 1
            if d >= market_start or line.split(b",",2)[1] in panel:
                out.write(line)
    if expected < 1000 or seen != expected:
        raise SourceError("Zeilenzahl der jüngsten CSV-Sitzung stimmt nicht mit der Datenbank überein")
    if dst.stat().st_size > 192*1024**2:
        raise SourceError("Öffentliche Preisdatei überschreitet das Cache-Limit")


def baseline(provider):
    ROOT.mkdir(parents=True,exist_ok=True)
    path, meta = ROOT/"prices.csv.gz", ROOT/"snapshot.json"
    if path.is_file() and meta.is_file():
        saved = json.loads(meta.read_text())
        age = (date.fromisoformat(provider.latest)-date.fromisoformat(saved["day"])).days
        if 0 <= age <= 7 and not (age == 0 and saved["revision"] != provider.ref):
            return path,saved
    rows = provider.query("SELECT COUNT(*) AS n FROM ohlcv WHERE date='"+provider.latest+"'",["n"],ttl=0)
    with TemporaryDirectory() as scratch:
        raw = Path(scratch)/"ohlcv.csv"
        print("Lade den öffentlichen OHLCV-Tabellenexport für die Wochenbasis.",flush=True)
        download("ohlcv",raw)
        tmp = path.with_suffix(".part")
        compact(raw,tmp,provider.latest,int(rows[0][0]))
        provider.check_revision()
        tmp.replace(path)
    saved = {"revision":provider.ref,"day":provider.latest}
    meta.write_text(json.dumps(saved))
    return path,saved


def historical_blocks(provider, symbols, first, last):
    path, meta = baseline(provider)
    provider.base_revision = meta["revision"]
    extended = meta["revision"] != provider.ref
    # The tail overlap captures late corrections; older history is rebuilt every week.
    tail = (date.fromisoformat(meta["day"])-timedelta(days=2)).isoformat()
    aliases = symbols | {s.replace(".","/") for s in symbols}
    for frame in pd.read_csv(path,chunksize=125000,keep_default_na=False):
        selected = frame.date.between(first,last) & frame.act_symbol.isin(aliases)
        if extended:
            selected &= frame.date < tail
        if selected.any():
            yield frame.loc[selected].copy()
    if extended:
        day = max(date.fromisoformat(first),date.fromisoformat(tail))
        while day <= date.fromisoformat(last):
            if day.weekday() < 5:
                q = f"SELECT {','.join(FIELDS)} FROM ohlcv WHERE date='{day}'"
                rows = provider.query(q,FIELDS)
                if rows:
                    block = pd.DataFrame([r for r in rows if r[1] in aliases],columns=FIELDS)
                    yield block
            day += timedelta(days=1)
        provider.check_revision()


def split_days(provider,first,last):
    with TemporaryDirectory() as scratch:
        path = Path(scratch)/"split.csv"
        download("split",path)
        with open(path,newline="") as f:
            reader = csv.DictReader(f)
            if not {"ex_date","act_symbol"}.issubset(reader.fieldnames or []):
                raise SourceError("Unerwarteter Split-Export")
            events = {(r["ex_date"],r["act_symbol"].replace("/",".")) for r in reader
                      if first <= r["ex_date"] <= last}
    provider.check_revision()
    return events
