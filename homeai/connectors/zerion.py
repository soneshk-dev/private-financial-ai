"""Zerion: EVM/Solana wallet tokens, DeFi positions (Aave etc.) and NFT floor value.

Ported from the old evm_balance.py Zerion path, including its three gotchas:
receipt tokens are hidden via ``flags.displayable``; loan values are positive
magnitudes stored as BORROWED; protocol display names are hyphenated into slugs.
"""
from __future__ import annotations

import base64
import json
import sqlite3
import time
from typing import Any

import httpx

from ..config import Config
from ..ledger.accounts import upsert_account
from ..ledger.balances import record_balance, replace_defi, replace_positions
from .base import SyncResult, parse_kv_conf, store_raw

API = "https://api.zerion.io/v1"
CHAINS = {"ethereum": "ethereum", "polygon": "polygon", "arbitrum": "arbitrum", "optimism": "optimism",
          "base": "base", "solana": "solana"}
RECEIPT_PREFIXES = ("aEth", "aArb", "aBas", "aOpt", "aPol", "variableDebt", "stableDebt")


class ZerionConnector:
    name = "zerion"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.api_key = parse_kv_conf(cfg.secrets_dir / cfg.zerion.conf_file).get("ZERION_API_KEY")

    def configured(self) -> bool:
        return bool(self.api_key) and not self.api_key.startswith("YOUR_")

    def _get(self, path: str, params: dict, retries: int = 3) -> httpx.Response | None:
        token = base64.b64encode(f"{self.api_key}:".encode()).decode()
        headers = {"accept": "application/json", "authorization": f"Basic {token}"}
        delay = 2.0
        for attempt in range(retries + 1):
            r = httpx.get(f"{API}/{path}", headers=headers, params=params, timeout=30)
            if r.status_code != 429 or attempt == retries:
                return r
            time.sleep(float(r.headers.get("Retry-After", delay)))
            delay *= 2
        return None

    def positions(self, address: str, chain: str) -> list[dict] | None:
        params = {"currency": "usd", "filter[trash]": "only_non_trash", "sort": "-value", "page[size]": 100}
        z = CHAINS.get(chain)
        if z:
            params["filter[chain_ids]"] = z
            if z != "solana":
                params["filter[positions]"] = "no_filter"
        r = self._get(f"wallets/{address}/positions/", params)
        if r is None or r.status_code != 200:
            raise RuntimeError(f"Zerion positions HTTP {getattr(r, 'status_code', '?')}: {getattr(r, 'text', '')[:200]}")
        return r.json().get("data", [])

    def nft_total(self, address: str, chain: str) -> float | None:
        r = self._get(f"wallets/{address}/nft-portfolio/", {"currency": "usd"}, retries=1)
        if r is None or r.status_code != 200:
            return None  # 202 = still indexing → unknown, keep prior value
        by_chain = ((r.json().get("data") or {}).get("attributes") or {}).get("positions_distribution_by_chain") or {}
        if not by_chain:
            return None
        z = CHAINS.get(chain, chain)
        return float(by_chain.get(z) or 0) if z in by_chain else float(sum(v or 0 for v in by_chain.values()))

    @staticmethod
    def normalize(positions: list[dict], chain: str) -> dict[str, Any]:
        tokens, protocols = [], {}
        token_total = defi_total = 0.0
        for p in positions or []:
            attr = p.get("attributes") or {}
            if attr.get("value") is None or not (attr.get("flags") or {}).get("displayable", True):
                continue
            value = float(attr["value"])
            ptype = attr.get("position_type") or "wallet"
            fi = attr.get("fungible_info") or {}
            symbol = fi.get("symbol") or "UNKNOWN"
            qty = float((attr.get("quantity") or {}).get("float") or 0)
            price = float(attr.get("price") or 0)
            rel = p.get("relationships") or {}
            network = (((rel.get("chain") or {}).get("data") or {}).get("id")) or chain
            addr = ""
            for impl in fi.get("implementations") or []:
                if impl.get("chain_id") == network:
                    addr = impl.get("address") or ""
                    break
            if ptype == "wallet":
                if value > 0.01 and not symbol.startswith(RECEIPT_PREFIXES):
                    tokens.append({"symbol": symbol, "name": fi.get("name") or symbol, "address": addr,
                                   "quantity": qty, "value": value, "price": price})
                    token_total += value
                continue
            appmeta = attr.get("application_metadata") or {}
            dapp_id = ((rel.get("dapp") or {}).get("data") or {}).get("id")
            proto_raw = attr.get("protocol") or appmeta.get("name") or dapp_id or "Unknown"
            slug = str(proto_raw).strip().lower().replace(" ", "-")
            pname = attr.get("protocol") or appmeta.get("name") or slug.replace("-", " ").title()
            if ptype == "loan":
                meta_type, usd, delta = "BORROWED", abs(value), -abs(value)
            elif ptype == "reward":
                meta_type, usd, delta = "CLAIMABLE", value, value
            else:
                meta_type, usd, delta = "SUPPLIED", value, value
            net_label = str(network).replace("-", " ").title()
            proto = protocols.setdefault((slug, net_label), {"protocol": pname, "protocol_slug": slug,
                                                              "network": net_label, "value": 0.0, "details": []})
            proto["value"] += delta
            defi_total += delta
            if abs(usd) > 0.01:
                proto["details"].append({"meta_type": meta_type, "symbol": symbol, "quantity": qty, "value": usd,
                                         "price": price, "contract": addr})
        return {"tokens": tokens, "protocols": list(protocols.values()), "token_total": token_total,
                "defi_total": defi_total}

    def sync(self, conn: sqlite3.Connection, cfg: Config, as_of: str) -> SyncResult:
        result = SyncResult(self.name)
        if not self.configured():
            result.skipped = True
            result.detail["reason"] = "not configured"
            return result
        for w in cfg.zerion.wallets:  # config-declared wallets become accounts
            upsert_account(conn, source="zerion", source_account_id=f"{w['chain']}:{w['address']}", name=w["name"],
                           kind="crypto_wallet", institution=w["chain"].title(),
                           meta={"chain": w["chain"], "address": w["address"]})
        wallets = conn.execute("SELECT id, name, meta FROM accounts WHERE source='zerion' AND is_active=1").fetchall()
        if not wallets:
            result.skipped = True
            result.detail["reason"] = "no wallets"
            return result
        synced = []
        for w in wallets:
            meta = json.loads(w["meta"] or "{}")
            chain, address = meta.get("chain", "ethereum"), meta["address"]
            raw = self.positions(address, chain)
            store_raw(conn, self.name, "positions", w["id"], raw)
            data = self.normalize(raw, chain)
            nft = self.nft_total(address, chain)
            if nft is None:  # keep last-known NFT value
                prev = conn.execute("SELECT value FROM positions_latest WHERE account_id=? AND key='NFTs'", (w["id"],)).fetchone()
                nft = float(prev["value"]) if prev else 0.0
            rows = [{"symbol": t["symbol"], "description": t["name"], "quantity": t["quantity"], "price": t["price"],
                     "value": t["value"], "asset_class": "crypto"} for t in data["tokens"]]
            if nft > 0:
                rows.append({"symbol": "NFTs", "description": "NFT floor value", "quantity": 1, "price": nft,
                             "value": nft, "asset_class": "nft"})
            # de-duplicate keys (same symbol on two contracts)
            seen: dict[str, dict] = {}
            for r in rows:
                k = r["symbol"]
                if k in seen:
                    seen[k]["value"] += r["value"]
                    seen[k]["quantity"] = (seen[k]["quantity"] or 0) + (r["quantity"] or 0)
                else:
                    seen[k] = r
            n_pos = replace_positions(conn, w["id"], as_of, seen.values(), "zerion")
            defi_rows = [dict(d, protocol=p["protocol"], protocol_slug=p["protocol_slug"], network=p["network"])
                         for p in data["protocols"] for d in p["details"]]
            n_defi = replace_defi(conn, w["id"], as_of, defi_rows)
            total = data["token_total"] + data["defi_total"] + nft
            record_balance(conn, w["id"], as_of, total, None, "zerion")
            synced.append({"wallet": w["name"], "tokens": n_pos, "defi": n_defi, "total": round(total, 2)})
            result.rows_written += n_pos + n_defi + 1
        result.detail["wallets"] = synced
        return result
