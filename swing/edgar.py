"""Optional point-in-time earnings release confirmation, never guessed sentiment."""
import json
import os
import re

from .data import timestamp


class Edgar:
    def __init__(self, reader):
        agent = os.environ.get("SEC_USER_AGENT","")
        if not re.search(r"\S+@\S+\.\S+",agent):
            raise ValueError("SEC_USER_AGENT benötigt eine Kontaktadresse")
        self.reader = reader
        self.headers = {"User-Agent":agent}
        raw = json.loads(reader.get("https://www.sec.gov/files/company_tickers.json",self.headers,86400))
        self.ids = {r["ticker"].replace("-","."): int(r["cik_str"]) for r in raw.values()}

    def earnings(self, symbol, previous_close, close):
        cik = self.ids.get(symbol)
        if not cik:
            return None
        data = json.loads(self.reader.get(f"https://data.sec.gov/submissions/CIK{cik:010}.json",self.headers,900))
        return self.find(data["filings"]["recent"],cik,previous_close,close)

    @staticmethod
    def find(rows,cik,previous_close,close):
        for form, items, accepted, acc in zip(rows["form"],rows["items"],rows["acceptanceDateTime"],rows["accessionNumber"],strict=True):
            if form != "8-K" or "2.02" not in [x.strip() for x in items.split(",")] or not accepted:
                continue
            t = timestamp(accepted)
            if t.tzinfo is None or not previous_close < t <= close:
                continue
            compact = acc.replace("-","")
            if not compact.isdigit():
                continue
            return {"keyword":"SEC 8-K Item 2.02 (Ergebnisveröffentlichung, Richtung aus Kursreaktion)",
                    "at":t.isoformat(),"url":f"https://www.sec.gov/Archives/edgar/data/{cik}/{compact}/{acc}-index.htm"}
        return None
