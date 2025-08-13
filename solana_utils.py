"""Solana utility functions (clean implementation).

Provides defensive helpers for:
 - Fetching SPL token balance for an owner (aggregates all token accounts)
 - Verifying a transfer delivered tokens to the treasury
All failures are logged (if SOLANA_DEBUG enabled) and return safe defaults.
"""

from __future__ import annotations

import os, json
from decimal import Decimal
import requests
from typing import Optional, Any

try:  # Prefer solders
    from solders.pubkey import Pubkey as PublicKey  # type: ignore
except Exception:
    try:
        from solana.publickey import PublicKey  # type: ignore
    except Exception:
        PublicKey = None  # type: ignore
try:
    from solana.rpc.api import Client  # type: ignore
except Exception:
    Client = None  # type: ignore

RPC_URL = os.getenv('SOLANA_RPC_URL', '')
SPL_TOKEN_MINT = os.getenv('SPL_TOKEN_MINT', '')
TREASURY = os.getenv('PLATFORM_TREASURY_WALLET', '')
LOG_DEBUG = os.getenv('SOLANA_DEBUG', '1') not in ('0', 'false', 'False', '')
client = Client(RPC_URL) if (RPC_URL and Client) else None


def _d(msg: str, **kv: Any):
    if not LOG_DEBUG:
        return
    try:
        extra = json.dumps(kv, default=str) if kv else ''
    except Exception:
        extra = str(kv)
    print(f"[solana_utils][debug] {msg}" + (f" | {extra}" if extra else ''))


BASE58_ALPHABET = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")


def _is_plausible_base58(s: str) -> bool:
    ok = isinstance(s, str) and 32 <= len(s) <= 44 and all(c in BASE58_ALPHABET for c in s)
    if not ok:
        _d('Not plausible base58', value=s)
    return ok


def _to_pubkey(maybe_key: str) -> Optional[PublicKey]:
    if not PublicKey:
        _d('PublicKey class unavailable')
        return None
    if not maybe_key or not _is_plausible_base58(maybe_key):
        return None
    try:
        if hasattr(PublicKey, 'from_string'):
            return PublicKey.from_string(maybe_key)  # type: ignore[attr-defined]
        if hasattr(PublicKey, 'from_base58'):
            return PublicKey.from_base58(maybe_key)  # type: ignore[attr-defined]
        return PublicKey(maybe_key)
    except Exception as e:
        _d('Pubkey construct error', err=str(e))
        return None


def _rpc_raw(method: str, params_list):
    """Low level raw RPC using requests (bypass solana-py mismatches)."""
    if not RPC_URL or 'your-quicknode-endpoint' in RPC_URL:
        _d('SOLANA_RPC_URL not configured correctamente', value=RPC_URL)
        return None
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params_list}
    try:
        r = requests.post(RPC_URL, json=payload, timeout=12)
        if r.status_code != 200:
            _d('raw rpc http status', status=r.status_code)
            return None
        return r.json()
    except Exception as e:
        _d('raw rpc network error', err=str(e))
        return None


def get_token_balance_owner(owner_address: str) -> Decimal:
    """Fetch SPL token balance via direct JSON-RPC (mint filter first, fallback programId).

    Elimina los errores de versiones mixtas ('Pubkey' no tiene 'encoding')
    usando strings base58 en el payload.
    """
    if not SPL_TOKEN_MINT or not owner_address:
        return Decimal('0')
    if not _is_plausible_base58(owner_address) or not _is_plausible_base58(SPL_TOKEN_MINT):
        return Decimal('0')

    # 1) Mint filter
    resp = _rpc_raw("getTokenAccountsByOwner", [owner_address, {"mint": SPL_TOKEN_MINT}, {"encoding": "jsonParsed"}])
    # 2) ProgramId filter fallback
    if not resp or 'result' not in resp:
        resp = _rpc_raw("getTokenAccountsByOwner", [owner_address, {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}, {"encoding": "jsonParsed"}])
    if not resp or 'result' not in resp:
        return Decimal('0')
    try:
        value = (resp.get('result') or {}).get('value') or []
        total = Decimal('0')
        for acc in value:
            try:
                info = acc['account']['data']['parsed']['info']
                if info.get('mint') != SPL_TOKEN_MINT:
                    continue
                amount_raw = info['tokenAmount']['amount']
                decimals = info['tokenAmount']['decimals']
                total += (Decimal(amount_raw) / (Decimal(10) ** Decimal(decimals)))
            except Exception:
                continue
        return total
    except Exception as e:
        _d('parse error', err=str(e))
        return Decimal('0')


def verify_transfer_signature(signature: str):
    if not signature or len(signature) < 20:
        return {'success': False, 'error': 'Invalid signature'}
    if not client or not PublicKey:
        return {'success': False, 'error': 'RPC not configured'}
    if not TREASURY:
        return {'success': False, 'error': 'Treasury unset'}
    tr_pk = _to_pubkey(TREASURY)
    if tr_pk is None:
        return {'success': False, 'error': 'Invalid treasury'}
    try:
        tx = client.get_transaction(signature, max_supported_transaction_version=0)
    except Exception as e:
        _d('get_transaction error', err=str(e))
        return {'success': False, 'error': 'RPC error'}
    if not tx or not tx.get('result'):
        return {'success': False, 'error': 'Transaction not found'}
    try:
        meta = tx['result']['meta']
        if not meta:
            return {'success': False, 'error': 'Missing meta'}
        post_bal = meta.get('postTokenBalances', [])
        pre_bal = meta.get('preTokenBalances', [])
        amount_to_treasury = Decimal('0')
        sender = None
        for pb in post_bal:
            try:
                if pb.get('mint') != SPL_TOKEN_MINT:
                    continue
                ui_post_s = (pb.get('uiTokenAmount') or {}).get('uiAmountString')
                ui_post = Decimal(ui_post_s) if ui_post_s else Decimal('0')
                match_pre = next((b for b in pre_bal if b.get('accountIndex') == pb.get('accountIndex')), None)
                ui_pre_s = (match_pre.get('uiTokenAmount') if match_pre else {}).get('uiAmountString') if match_pre else None
                ui_pre = Decimal(ui_pre_s) if ui_pre_s else Decimal('0')
                delta = ui_post - ui_pre
                owner = pb.get('owner')
                if owner == TREASURY and delta > 0:
                    amount_to_treasury += delta
                if delta < 0:
                    sender = owner
            except Exception:
                continue
        if amount_to_treasury <= 0:
            return {'success': False, 'error': 'No tokens delivered'}
        return {'success': True, 'amount_tokens': float(amount_to_treasury), 'sender': sender}
    except Exception as e:
        _d('verify parse error', err=str(e))
        return {'success': False, 'error': 'Verification failed'}
