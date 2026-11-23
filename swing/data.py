"""Read-only market endpoints. No broker or order client."""
import gzip
import hashlib
import pathlib
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

from .market import directory

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
                with urlopen(req, timeout=75) as response:
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
