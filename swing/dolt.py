"""Anonymous, read-only DoltHub SQL API. One immutable database revision per run."""
from datetime import date, timedelta
import json
import re
from urllib.parse import urlencode

import pandas as pd

from .data import COLS, SourceError

SOURCE = "DoltHub post-no-preference/stocks"
API = "https://www.dolthub.com/api/v2/databases/post-no-preference/stocks/sql"
FIELDS = ["date", "act_symbol", *COLS]
LIMIT = 100000


class Incomplete(SourceError):
    """A read may be retried using a smaller date range."""


class Dolt:
    def __init__(self, reader):
        self.reader = reader
        self.ref = "master"
        snapshot = self.query("SELECT DOLT_HASHOF('HEAD') AS revision, MAX(date) AS day FROM ohlcv",
                              ["revision", "day"], limit=2, ttl=0)
        if len(snapshot) != 1 or not re.fullmatch("[0-9a-v]{32}", snapshot[0][0]):
            raise SourceError("Ungültige Datenrevision")
        self.ref, self.latest = snapshot[0]
        date.fromisoformat(self.latest)
        self.frames = {}

    def query(self, sql, fields, limit=LIMIT, ttl=86400):
        url = API + "?" + urlencode(dict(ref="master", q=sql, limit=limit, timeout_ms=60000))
        data = json.loads(self.reader.get(url, ttl=ttl)).get("data", {})
        status = data.get("status")
        if status in {"row_limit", "timeout"}:
            raise Incomplete("Zeit- oder Zeilenlimit der Datenquelle")
        if status != "success" or [col["name"] for col in data.get("columns", [])] != fields:
            raise SourceError("Ungültige Antwort der SQL-Datenquelle")
        rows = data["rows"]
        if len(rows) >= limit:
            raise Incomplete("Zeilengrenze erreicht")
        if any(len(row) != len(fields) for row in rows):
            raise SourceError("Unvollständige Datenzeile")
        return rows

    def interval(self, first, last, table, fields, date_col, extra=""):
        where = f"{date_col} BETWEEN '{first}' AND '{last}'"
        sql = f"SELECT {','.join(fields)} FROM {table} AS OF '{self.ref}' WHERE {where}{extra}"
        try:
            yield self.query(sql, fields)
        except Incomplete:
            if first == last:
                raise
            middle = first + (last-first)//2
            yield from self.interval(first, middle, table, fields, date_col, extra)
            yield from self.interval(middle+timedelta(days=1), last, table, fields, date_col, extra)

    def prepare(self, symbols, first, last, panel=False):
        """Collect period batches once, keeping only requested listings in memory."""
        if last > self.latest:
            raise SourceError(f"Tageskurse erst bis {self.latest} verfügbar")
        universe = set(symbols)
        start, end = date.fromisoformat(first), date.fromisoformat(last)
        extra = " AND volume>0"
        if panel:
            if not universe or not all(re.fullmatch(r"[A-Z]{1,6}(?:\.[A-Z])?", s) for s in universe):
                raise ValueError("Ungültiges Aktienpanel")
            extra += " AND act_symbol IN (" + ",".join("'" + s + "'" for s in sorted(universe)) + ")"
        splits = set()
        for rows in self.interval(start,end,"split",["ex_date","act_symbol"],"ex_date"):
            splits.update((d,s.replace("/",".")) for d,s in rows)
        chunks = []
        day = start
        while day <= end:
            # Weekly entire-market reads, longer reads for the small validation panel.
            stop = min(end, day+timedelta(days=89 if panel else 6-day.weekday()))
            for rows in self.interval(day,stop,"ohlcv",FIELDS,"date",extra):
                kept = [r for r in rows if r[1].replace("/",".") in universe]
                if kept:
                    df = pd.DataFrame(kept, columns=FIELDS)
                    df["act_symbol"] = df.act_symbol.str.replace("/",".",regex=False)
                    df[COLS] = df[COLS].apply(pd.to_numeric, errors="coerce")
                    if splits:
                        ix = [(d,s) in splits for d,s in zip(df.date,df.act_symbol)]
                        df.loc[ix,COLS] = float("nan")
                    df["date"] = pd.to_datetime(df.date,format="%Y-%m-%d",errors="raise")
                    chunks.append(df)
            day = stop+timedelta(days=1)
        if not chunks:
            self.frames = {}
            return
        frame = pd.concat(chunks,ignore_index=True).set_index("date").sort_index()
        self.frames = {s:g[COLS] for s,g in frame.groupby("act_symbol",sort=False)}

    def bars(self, symbols, first, cutoff):
        last = cutoff.date().isoformat()
        return {s:self.frames[s].loc[first:last] for s in symbols if s in self.frames}
