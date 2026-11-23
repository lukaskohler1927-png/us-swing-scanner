"""Private recipient pairing and at-most-once delivery. No credentials in error messages."""
import hmac
import json
import os
import re
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .market import NY, bounds, next_day
from .strategy import SIDE


class TelegramFailure(RuntimeError):
    pass


def api(method, body):
    token = os.getenv("TELEGRAM_BOT_TOKEN","")
    if not re.fullmatch(r"\d+:[\w-]+",token):
        raise TelegramFailure("Telegram-Token fehlt oder hat ungültiges Format")
    req = Request(f"https://api.telegram.org/bot{token}/{method}",
                  data=json.dumps(body).encode(), headers={"Content-Type":"application/json"})
    try:
        with urlopen(req,timeout=15) as r:
            data = json.load(r)
    except HTTPError as e:
        raise TelegramFailure(f"Telegram HTTP {e.code}") from None
    except (OSError, URLError, ValueError):
        raise TelegramFailure("Telegram-Antwort ungewiss") from None
    if not data.get("ok"):
        raise TelegramFailure("Telegram-Aufruf abgewiesen")
    return data["result"]


def pair(state, now):
    if state["chat"]:
        return
    code = os.getenv("TELEGRAM_PAIR_CODE","")
    if len(code)<16:
        raise ValueError("Privater Kopplungscode benötigt mindestens 16 Zeichen")
    chats = set()
    for upd in api("getUpdates",{"limit":100,"timeout":0,"allowed_updates":["message"]}):
        msg = upd.get("message",{})
        chat = msg.get("chat",{})
        if chat.get("type") != "private" or msg.get("from",{}).get("id") != chat.get("id"):
            continue
        age = now.timestamp()-msg.get("date",0)
        if 0 <= age <= 900 and hmac.compare_digest(msg.get("text","").strip().encode(),("/start "+code).encode()):
            chats.add(chat["id"])
    if len(chats) != 1:
        raise ValueError("Genau ein passender privater /start-Code innerhalb von 15 Minuten erforderlich")
    state["chat"] = chats.pop()


def formatted(p, now, paper):
    s = p["side"]
    e = p["entry"]
    fmt = lambda x: f"{x:.2f} USD ({s*(x/e-1):+.2%} Positionsrendite)"
    cl = bounds(p["day"])[1]
    expiry = bounds(next_day(p["day"]))[0]
    age = (now-cl).total_seconds()/3600
    label = "PAPER · " if paper else ""
    return (f"{'🟢' if s==1 else '🔴'} {label}{SIDE[s]} SIGNAL – {p['symbol']}\n"
            f"{p['asset']}: {p['name']}\nStrategie: {p['strategy']}\n"
            f"Einstieg zur nächsten Eröffnung: {p['lo']:.2f}–{p['hi']:.2f} USD (Referenz {e:.2f})\n"
            f"Stop-Loss: {fmt(p['stop'])}\nTake-Profit: {fmt(p['target'])}\n"
            f"Chance/Risiko netto am ungünstigen Rand: {p['rr']:.2f}:1\n"
            f"Haltedauer: 2–5 Handelstage, frühere Ausstiege möglich\nSignal-Score: {p['score']}/100\n"
            f"Grund: {p['reason']}\nSpread unbekannt. Geld-/Briefkurs vor Ausführung bei IBKR prüfen.\n"
            f"Kursstand: {cl.astimezone(NY):%d.%m.%Y %H:%M %Z}, vor {age:.1f} h (Tagesdaten)\n"
            f"Gültig bis: {expiry.astimezone(NY):%d.%m.%Y %H:%M %Z}, nur innerhalb der Zone.\nKurse: DoltHub post-no-preference/stocks (CC BY-SA 4.0)."
            + ("\nShort: Leihbarkeit und Leihsatz bei IBKR ungeprüft. Squeeze- und Gap-Risiko." if s<0 else "")
            + ("\nQuelle: "+p["event"]["url"] if p.get("event") and p["event"]["url"] else ""))


def reserve(state, key, message, kind="signal", expires=None):
    if state["chat"] and not any(x["key"]==key for x in state["outbox"]):
        state["outbox"].append({"key":key,"text":message,"kind":kind,"expires":expires,"status":"queued"})


def dispatch(state, persist, now):
    failed = 0
    for m in state["outbox"]:
        if m["status"] != "queued":
            continue
        if m.get("expires") and datetime.fromisoformat(m["expires"]) <= now():
            m["status"] = "expired"
            persist(state)
            continue
        m["status"] = "reserved"
        persist(state)
        try:
            api("sendMessage",{"chat_id":state["chat"],"text":m["text"],
                               "link_preview_options":{"is_disabled":True}})
        except TelegramFailure:
            m["status"] = "uncertain"
            failed += 1
        else:
            m["status"] = "sent"
        persist(state)
    if failed:
        raise TelegramFailure("Telegram-Zustellung unbestätigt. Siehe Workflow-Status.")
