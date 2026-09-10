"""Telegram Bot API sender. Credentials: secrets_dir/telegram.conf with
TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."""
from __future__ import annotations

import httpx

from ..config import Config
from ..connectors.base import parse_kv_conf


def creds(cfg: Config) -> tuple[str | None, str | None]:
    c = parse_kv_conf(cfg.secrets_dir / cfg.telegram.conf_file)
    return c.get("TELEGRAM_BOT_TOKEN"), c.get("TELEGRAM_CHAT_ID")


def configured(cfg: Config) -> bool:
    t, c = creds(cfg)
    return bool(t and c)


def send(cfg: Config, text: str, parse_mode: str | None = "Markdown") -> dict:
    token, chat_id = creds(cfg)
    if not token or not chat_id:
        return {"ok": False, "error": "telegram not configured"}
    out = {"ok": True, "parts": 0}
    for part in _chunks(text, 3800):
        body = {"chat_id": chat_id, "text": part, "disable_web_page_preview": True}
        if parse_mode:
            body["parse_mode"] = parse_mode
        r = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage", json=body, timeout=30)
        if r.status_code != 200 and parse_mode:  # markdown parse failure → resend plain
            body.pop("parse_mode")
            r = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage", json=body, timeout=30)
        if r.status_code != 200:
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        out["parts"] += 1
    return out


def _chunks(text: str, n: int):
    while text:
        cut = text.rfind("\n", 0, n) if len(text) > n else len(text)
        cut = cut if cut > 0 else n
        yield text[:cut]
        text = text[cut:].lstrip("\n")
