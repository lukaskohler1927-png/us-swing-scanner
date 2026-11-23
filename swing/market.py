"""XNYS regular sessions, timestamps, and Nasdaq Trader's two official directories."""
import csv
import io
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xc
import pandas as pd

NY = ZoneInfo("America/New_York")


@lru_cache(maxsize=1)
def calendar():
    return xc.get_calendar("XNYS", start="2010-01-01", end="2035-12-31")


def sessions(first, last):
    return calendar().sessions_in_range(pd.Timestamp(first), pd.Timestamp(last)).tz_localize(None)


def bounds(day):
    cal = calendar()
    return cal.session_open(day).to_pydatetime(), cal.session_close(day).to_pydatetime()


def next_day(day):
    return calendar().next_session(pd.Timestamp(day)).date().isoformat()


def run_day(now, mode):
    """Old schedules must never issue a plan retroactively."""
    local = now.astimezone(NY)
    day = local.date().isoformat()
    if mode == "catchup":
        if (local.hour,local.minute) >= (9,30):
            return None
        prior = calendar().date_to_session(pd.Timestamp(day)-pd.Timedelta(days=1),direction="previous")
        return prior.date().isoformat() if now < bounds(next_day(prior))[0] else None
    if not calendar().is_session(day):
        return None
    op, cl = bounds(day)
    return day if now >= cl + timedelta(minutes=45) else None


@dataclass(frozen=True)
class Listing:
    symbol: str
    name: str
    exchange: str
    asset: str


BAD = re.compile(r"\b(?:warrants?|units?|rights?|preferred|preference|depositary shares? (?:each|representing)|notes?|debentures?|bonds?|acquisition corp(?:oration)?|closed.end|beneficial interest in|when issued|subordinated|due 20\d\d)\b", re.I)
COMMON = re.compile(r"common (?:stock|shares?)|ordinary shares?|american deposit(?:a|o)ry|\bADR\b|shares of beneficial interest|capital stock|equity shares?|class [a-z] (?:shares|stock)", re.I)
LEVERED = re.compile(r"\b(?:inverse|ultra\w*|bear|bull|leveraged|short|[1234]x|2 x|3 x|daily target)\b", re.I)


def directory(data, kind, now, include_etfs=False):
    lines = data.decode("utf-8-sig").strip().splitlines()
    if not lines or not lines[-1].startswith("File Creation Time:"):
        raise ValueError("unvollständiges Nasdaq-Verzeichnis")
    match = re.search(r"(\d{10}:?\d{2})", lines[-1])
    if not match:
        raise ValueError("Nasdaq-Zeitstempel fehlt")
    stamp = datetime.strptime(match[1].replace(":", ""), "%m%d%Y%H%M").replace(tzinfo=NY)
    if not -timedelta(hours=2) <= now - stamp <= timedelta(days=5):
        raise ValueError("Nasdaq-Verzeichnis veraltet oder aus der Zukunft")
    rows = csv.DictReader(io.StringIO("\n".join(lines[:-1])), delimiter="|")
    result = {}
    tally = Counter()
    nasdaq = kind == "nasdaqlisted"
    required = {"Security Name", "Test Issue", "ETF", "Symbol" if nasdaq else "ACT Symbol",
                "Financial Status" if nasdaq else "Exchange"}
    if not required.issubset(rows.fieldnames or ()):
        raise ValueError("Nasdaq-Schema unbekannt")
    for row in rows:
        tally["rows"] += 1
        name = row["Security Name"]
        etf = row["ETF"] == "Y"
        exchange = "NASDAQ" if nasdaq else {"N": "NYSE", "A": "NYSE American", "P": "NYSE Arca"}.get(row["Exchange"])
        if (row["Test Issue"] != "N" or row["ETF"] not in {"N", "Y"} or not exchange
                or (nasdaq and row["Financial Status"] != "N")
                or (exchange == "NYSE Arca" and not etf)):
            continue
        if etf:
            if not include_etfs or LEVERED.search(name):
                continue
        elif BAD.search(name) or not COMMON.search(name):
            continue
        symbol = row["Symbol" if nasdaq else "ACT Symbol"].replace("/", ".")
        if re.fullmatch(r"[A-Z]{1,6}(?:\.[A-Z])?", symbol):
            result[symbol] = Listing(symbol, name, exchange, "ETF" if etf else "Aktie")
    return result, tally, stamp.isoformat()
