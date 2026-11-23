"""Small encrypted ledger. Persist the send reservation before crossing the Telegram boundary."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess

from cryptography.fernet import Fernet

ROOT = Path("runtime")


def blank():
    return {"schema":1, "chat":None, "active":[], "closed":[], "days":[], "outbox":[],
            "last_scan":None, "validation":None, "opencheck":None}


def cipher():
    value = os.getenv("STATE_KEY") or os.getenv("TELEGRAM_BOT_TOKEN") or ""
    if len(value) < 24:
        raise ValueError("STATE_KEY oder Telegram-Token benötigt mindestens 24 Zeichen")
    digest = hashlib.sha256(("swing-ledger-v1/" + value).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def read():
    p = ROOT / "ledger.enc"
    if not p.exists():
        if (ROOT / "status.json").exists():
            raise RuntimeError("Journal fehlt bei vorhandenem Status")
        return blank()
    data = json.loads(cipher().decrypt(p.read_bytes()))
    if data.get("schema") != 1:
        raise ValueError("Unbekanntes Journalformat")
    return data


def save(data, status=None):
    ROOT.mkdir(exist_ok=True)
    enc = ROOT / "ledger.enc"
    tmp = enc.with_suffix(".part")
    tmp.write_bytes(cipher().encrypt(json.dumps(data,allow_nan=False,separators=(",",":")).encode()))
    tmp.replace(enc)
    if status is not None:
        path = ROOT / "status.json"
        path.write_text(json.dumps(status,indent=2,allow_nan=False)+"\n")
    if os.getenv("PUBLISH_LEDGER") == "1":
        files = [str(enc)]
        if status is not None:
            files.append(str(ROOT / "status.json"))
        subprocess.run(["git","add","-f","--",*files],check=True)
        subprocess.run(["git","commit","-qm","Publish scanner research checkpoint"],check=True)
        # An optimistic non-force push is required before any notification can proceed.
        subprocess.run(["git","push","--quiet","origin","HEAD:refs/heads/"+os.environ["DEFAULT_BRANCH"]],check=True)
