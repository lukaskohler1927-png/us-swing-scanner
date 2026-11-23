"""Read-only market endpoints. No broker or order client."""
import gzip
import hashlib
import json
import os
import pathlib
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from .market import NY, bounds, directory

BASE = "https://data.alpaca.markets"
NASDAQ = "https://www.nasdaqtrader.com/dynamic/SymDir/"
COLS = ["open", "high", "low", "close", "volume"]


class SourceError(RuntimeError):
    pass


class Reader:
    def __init__(self, cache=".cache", delay=.36):
        self.cache = pathlib.Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.last = 0

    def get(self, url, headers=None, ttl=0):
        path = self.cache / (hashlib.sha256(url.encode()).hexdigest() + ".gz")
        if ttl and path.exists() and time.time() - path.stat().st_mtime < ttl:
            try:
                return gzip.decompress(path.read_bytes())
            except (EOFError, OSError):
                path.unlink(missing_ok=True)
        for i in range(4):
            time.sleep(max(0, self.last + self.delay - time.monotonic()))
            self.last = time.monotonic()
            wait = 2 ** i
            try:
                req = Request(url, headers={"User-Agent": "PersonalSwingResearch/1.0",
                              "Accept-Encoding": "gzip", **(headers or {})})
                with urlopen(req, timeout=30) as response:
                    buf = response.read()
                    if response.headers.get("Content-Encoding") == "gzip":
                        buf = gzip.decompress(buf)
                if ttl:
                    tmp = path.with_suffix(".part")
                    tmp.write_bytes(gzip.compress(buf, compresslevel=1))
                    tmp.replace(path)
                return buf
            except HTTPError as e:
                if e.code not in {408, 429, 500, 502, 503, 504}:
                    raise SourceError(f"Datenquelle HTTP {e.code}") from None
                retry = e.headers.get("Retry-After", "")
                if retry.isdigit():
                    wait = max(wait, int(retry))
                if wait > 90:
                    raise SourceError("Datenanbieter fordert längere Abrufpause") from None
            except (URLError, TimeoutError, OSError, EOFError):
                pass
            if i < 3:
                time.sleep(wait)
        raise SourceError("Datenquelle nach vier Versuchen nicht erreichbar")


def universe(reader, now, etfs=False):
    found, stamps = {}, {}
    for name in ("nasdaqlisted", "otherlisted"):
        block, counts, stamp = directory(reader.get(NASDAQ + name + ".txt", ttl=900), name, now, etfs)
        if counts["rows"] < 1000:
            raise SourceError("Nasdaq-Verzeichnis unerwartet klein")
        found.update(block)
        stamps[name] = stamp
    return found, stamps


def timestamp(value):
    return pd.Timestamp(value).to_pydatetime()


class Alpaca:
    def __init__(self, reader):
        self.reader = reader
        self.headers = {"APCA-API-KEY-ID": os.environ["ALPACA_KEY_ID"],
                        "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"]}

    def pages(self, path, params, ttl=3600):
        token = None
        seen = set()
        for _ in range(2000):
            args = dict(params)
            if token:
                args["page_token"] = token
            page = json.loads(self.reader.get(BASE + path + "?" + urlencode(args), self.headers, ttl))
            yield page
            token = page.get("next_page_token")
            if not token:
                return
            if token in seen:
                raise SourceError("wiederholte Pagination")
            seen.add(token)
        raise SourceError("Pagination unvollständig")

    def bars(self, symbols, first, cutoff, timeframe="1Day", adjustment="split"):
        result = {}
        if not symbols:
            return result
        args = {"symbols": ",".join(symbols), "timeframe": timeframe, "start": first,
                "end": cutoff.isoformat(), "feed": "sip", "adjustment": adjustment,
                "asof": "-", "limit": 10000}
        for page in self.pages("/v2/stocks/bars", args):
            if not isinstance(page.get("bars"), dict):
                raise SourceError("ungültige Kursantwort")
            for symbol, rows in page["bars"].items():
                result.setdefault(symbol, []).extend(rows)
        frames = {}
        for symbol, rows in result.items():
            if not rows:
                continue
            df = pd.DataFrame(rows).rename(columns=dict(zip("ohlcv", COLS)))
            index = pd.to_datetime(df["t"], utc=True).dt.tz_convert(NY)
            df.index = index.dt.normalize().dt.tz_localize(None) if timeframe == "1Day" else index
            frames[symbol] = df[COLS]
        return frames

    def spread(self, symbol, day):
        """Observed NBBO sample in final regular-session minute, before auction."""
        _, cl = bounds(day)
        finish = cl - timedelta(seconds=5)
        start = finish - timedelta(seconds=55)
        args = {"symbols": symbol, "start": start.isoformat(), "end": finish.isoformat(),
                "feed": "sip", "sort": "desc", "limit": 30}
        page = next(self.pages("/v2/stocks/quotes", args))
        values = []
        times = set()
        for q in (page.get("quotes") or {}).get(symbol, []):
            t = timestamp(q["t"])
            b, a = q["bp"], q["ap"]
            if (start <= t <= finish and t not in times and 0 < b < a and
                    q.get("bs", 0) > 0 and q.get("as", 0) > 0):
                times.add(t)
                values.append((a-b) / ((a+b)/2))
        if len(values) < 3:
            return None
        return float(pd.Series(values).quantile(.9))

    def opening(self, symbols, day):
        op, _ = bounds(day)
        frames = self.bars(symbols, op.isoformat(), op + timedelta(seconds=59), "1Min", "raw")
        return {s: float(df.iloc[0].open) for s, df in frames.items()
                if not df.empty and df.index[0].to_pydatetime() == op}

    def news(self, day):
        op, close = bounds(day)
        first = close - timedelta(days=4)
        result = {}
        for page in self.pages("/v1beta1/news", {"start": first.isoformat(), "end": close.isoformat(),
                              "limit": 50, "sort": "desc", "include_content": "false"}):
            for story in page.get("news") or []:
                created = timestamp(story["created_at"])
                updated = timestamp(story.get("updated_at") or story["created_at"])
                # Never project a revised story into an earlier signal.
                if not first <= created <= updated <= close:
                    continue
                symbols = story.get("symbols") or []
                if len(symbols) != 1:
                    continue
                for symbol in symbols:
                    result.setdefault(symbol, []).append((created, story["headline"], story.get("url","")))
        return result
