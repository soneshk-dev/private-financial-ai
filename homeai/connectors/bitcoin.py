"""Bitcoin: derive addresses locally from xpubs / multisig descriptors and sum
balances via public block explorers. Only totals are stored, never addresses.

Ported from the old bitcoin_balance.py (single-sig xpub/ypub/zpub, wsh(sortedmulti)
descriptors, BIP389 <0;1> paths). Requires ``bip-utils`` and ``base58``.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from typing import Any

import httpx

from ..config import Config
from ..ledger.accounts import upsert_account
from ..ledger.balances import record_balance, replace_positions
from .base import SyncResult, parse_kv_conf

BLOCKSTREAM = "https://blockstream.info/api"
MEMPOOL = "https://mempool.space/api"


def is_descriptor(v: str) -> bool:
    return v.startswith(("wsh(", "sh(", "wpkh(", "pkh(", "tr("))


def parse_descriptor(desc: str) -> dict[str, Any]:
    info: dict[str, Any] = {"type": None, "threshold": None, "xpubs": [], "is_multisig": False,
                            "bip389": "/<0;1>/*" in desc or "/<0,1>/*" in desc}
    if desc.startswith(("wsh(sortedmulti", "wsh(multi")):
        info.update(type="p2wsh", is_multisig=True)
    elif desc.startswith("sh(wsh("):
        info.update(type="p2sh-p2wsh", is_multisig=True)
    elif desc.startswith(("sh(multi", "sh(sortedmulti")):
        info.update(type="p2sh", is_multisig=True)
    elif desc.startswith("wpkh("):
        info["type"] = "p2wpkh"
    elif desc.startswith("sh(wpkh("):
        info["type"] = "p2sh-p2wpkh"
    elif desc.startswith("pkh("):
        info["type"] = "p2pkh"
    elif desc.startswith("tr("):
        info["type"] = "p2tr"
    if info["is_multisig"]:
        m = re.search(r"multi\((\d+)", desc)
        info["threshold"] = int(m.group(1)) if m else None
    for m in re.finditer(r"(\[([a-fA-F0-9]+)(/[^\]]+)?\])?([xyz]pub[a-zA-Z0-9]+)(/[<\d;,>/*]+)?", desc):
        info["xpubs"].append({"xpub": m.group(4), "derivation": m.group(5)})
    return info


def _to_xpub(key: str) -> str:
    import base58
    if key.startswith(("zpub", "ypub")):
        decoded = base58.b58decode_check(key)
        return base58.b58encode_check(bytes.fromhex("0488B21E") + decoded[4:]).decode()
    return key


def _hash160(b: bytes) -> bytes:
    return hashlib.new("ripemd160", hashlib.sha256(b).digest()).digest()


def _addr_from_pubkey(pub: bytes, addr_type: str) -> str:
    import base58
    from bip_utils import SegwitBech32Encoder
    if addr_type == "p2wpkh":
        return SegwitBech32Encoder.Encode("bc", 0, _hash160(pub))
    if addr_type == "p2sh-p2wpkh":
        return base58.b58encode_check(bytes([0x05]) + _hash160(bytes([0x00, 0x14]) + _hash160(pub))).decode()
    return base58.b58encode_check(bytes([0x00]) + _hash160(pub)).decode()


def derive_single(xpub: str, index: int, change: bool, addr_type: str | None = None) -> str:
    from bip_utils import Bip32Slip10Secp256k1
    if addr_type is None:
        addr_type = {"zpub": "p2wpkh", "ypub": "p2sh-p2wpkh"}.get(xpub[:4], "p2pkh")
    node = Bip32Slip10Secp256k1.FromExtendedKey(_to_xpub(xpub))
    path = f"{index}" if node.Depth() == 4 else f"{1 if change else 0}/{index}"
    pub = node.DerivePath(path).PublicKey().RawCompressed().ToBytes()
    return _addr_from_pubkey(pub, addr_type)


def derive_multisig(info: dict, index: int, change: bool) -> str:
    import base58
    from bip_utils import Bip32Slip10Secp256k1, SegwitBech32Encoder
    pubkeys = []
    for x in info["xpubs"]:
        node = Bip32Slip10Secp256k1.FromExtendedKey(_to_xpub(x["xpub"]))
        d = x.get("derivation") or ""
        if info["bip389"] or "<0;1>" in d or "<0,1>" in d or node.Depth() == 3:
            path = f"{1 if change else 0}/{index}"
        else:
            path = f"{index}"
        pubkeys.append(node.DerivePath(path).PublicKey().RawCompressed().ToBytes())
    pubkeys.sort()
    script = bytes([0x50 + info["threshold"]]) + b"".join(bytes([len(pk)]) + pk for pk in pubkeys) \
        + bytes([0x50 + len(pubkeys)]) + bytes([0xAE])
    if info["type"] == "p2wsh":
        return SegwitBech32Encoder.Encode("bc", 0, hashlib.sha256(script).digest())
    if info["type"] == "p2sh-p2wsh":
        wp = bytes([0x00, 0x20]) + hashlib.sha256(script).digest()
        return base58.b58encode_check(bytes([0x05]) + _hash160(wp)).decode()
    if info["type"] == "p2sh":
        return base58.b58encode_check(bytes([0x05]) + _hash160(script)).decode()
    raise ValueError(f"unsupported multisig type {info['type']}")


def derive(wallet_value: str, index: int, change: bool) -> str:
    if is_descriptor(wallet_value):
        info = parse_descriptor(wallet_value)
        if info["is_multisig"]:
            return derive_multisig(info, index, change)
        return derive_single(info["xpubs"][0]["xpub"], index, change, info["type"])
    return derive_single(wallet_value, index, change)


def address_balance(address: str) -> tuple[int, int]:
    for base in (BLOCKSTREAM, MEMPOOL):
        try:
            r = httpx.get(f"{base}/address/{address}", timeout=15)
            if r.status_code == 200:
                d = r.json()
                cs, ms = d.get("chain_stats", {}), d.get("mempool_stats", {})
                return (cs.get("funded_txo_sum", 0) - cs.get("spent_txo_sum", 0),
                        ms.get("funded_txo_sum", 0) - ms.get("spent_txo_sum", 0))
            if r.status_code == 429:
                time.sleep(2)
        except httpx.HTTPError:
            continue
    return 0, 0


def btc_price() -> float:
    for url, pick in (("https://mempool.space/api/v1/prices", lambda j: j.get("USD", 0)),
                      ("https://api.coinbase.com/v2/prices/BTC-USD/spot", lambda j: float(j["data"]["amount"]))):
        try:
            r = httpx.get(url, timeout=10)
            if r.status_code == 200:
                return float(pick(r.json()))
        except (httpx.HTTPError, KeyError, ValueError):
            continue
    return 0.0


def scan_wallet(value: str, gap_limit: int = 50) -> dict[str, int]:
    out = {"confirmed": 0, "unconfirmed": 0, "used": 0}
    for change in (False, True):
        empty = index = 0
        while empty < gap_limit:
            c, u = address_balance(derive(value, index, change))
            if c + u > 0:
                out["confirmed"] += c
                out["unconfirmed"] += u
                out["used"] += 1
                empty = 0
            else:
                empty += 1
            index += 1
    return out


class BitcoinConnector:
    name = "bitcoin"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.wallets = parse_kv_conf(cfg.secrets_dir / cfg.bitcoin.xpub_file)

    def configured(self) -> bool:
        return bool(self.wallets)

    def sync(self, conn: sqlite3.Connection, cfg: Config, as_of: str) -> SyncResult:
        result = SyncResult(self.name)
        if not self.configured():
            result.skipped = True
            result.detail["reason"] = "no wallets configured"
            return result
        price = btc_price()
        if price <= 0:
            raise RuntimeError("could not fetch BTC price")
        details = []
        for name, value in self.wallets.items():
            scan = scan_wallet(value, cfg.bitcoin.gap_limit)
            btc = (scan["confirmed"] + scan["unconfirmed"]) / 1e8
            usd = btc * price
            aid = upsert_account(conn, source="bitcoin", source_account_id=name, name=name, kind="crypto_wallet",
                                 institution="Bitcoin")
            replace_positions(conn, aid, as_of, [{"symbol": "BTC", "description": "Bitcoin", "quantity": btc,
                                                  "price": price, "value": usd, "asset_class": "crypto"}], "bitcoin")
            record_balance(conn, aid, as_of, usd, None, "bitcoin")
            details.append({"wallet": name, "btc": round(btc, 8), "usd": round(usd, 2), "addresses": scan["used"]})
            result.rows_written += 2
        result.detail = {"price": price, "wallets": details}
        return result


def quick_price_update(conn: sqlite3.Connection, as_of: str) -> dict[str, Any]:
    """Re-price BTC positions without rescanning addresses."""
    price = btc_price()
    if price <= 0:
        return {"ok": False}
    rows = conn.execute("SELECT account_id, quantity FROM positions_latest WHERE symbol = 'BTC' AND source='bitcoin'").fetchall()
    for r in rows:
        usd = float(r["quantity"] or 0) * price
        replace_positions(conn, r["account_id"], as_of, [{"symbol": "BTC", "description": "Bitcoin",
                                                          "quantity": r["quantity"], "price": price, "value": usd,
                                                          "asset_class": "crypto"}], "bitcoin")
        record_balance(conn, r["account_id"], as_of, usd, None, "bitcoin")
    return {"ok": True, "price": price, "wallets": len(rows)}
