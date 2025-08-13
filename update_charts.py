"""Background updater for SPL token metrics (price, volume, liquidity, etc.).

This file previously contained nested / duplicated definitions that prevented
`start_background_updater` from being imported. It is now a clean, minimal and
defensive implementation. All network / DB failures are swallowed with log
messages so the main Flask app can still start.
"""

from __future__ import annotations

import os
import requests
import time
import threading
from dotenv import load_dotenv

load_dotenv()

from db_module import AccountsDBTools
from pricin_update import get_dexscreener_price  # reuse robust logic

TOKEN_ADDRESS_ENV = 'SPL_TOKEN_MINT'
UPDATE_INTERVAL = int(os.getenv('TOKEN_PRICE_UPDATE_INTERVAL_SEC', '120'))


def get_dexscreener_data(token_address: str, chain: str = 'solana'):
    """Fetch summary metrics for a token from Dexscreener.

    Returns dict or None. Never raises.
    """
    if not token_address:
        return None
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()
        pairs = [p for p in data.get('pairs', []) if isinstance(p, dict) and p.get('chainId') == chain]
        if not pairs:
            return None
        # Use robust price function (already filters outliers for stables)
        robust_price = get_dexscreener_price(token_address, chain)
        def safe_float(v):
            try:
                return float(v) if v is not None else 0.0
            except Exception:
                return 0.0
        # Pick highest liquidity for other metrics
        def liq_usd(p):
            try:
                return float((p.get('liquidity') or {}).get('usd') or 0)
            except Exception:
                return 0.0
        best = max(pairs, key=liq_usd)
        metrics = {
            'price_usd': safe_float(robust_price),
            'market_cap_usd': safe_float(best.get('marketCap')),
            'fdv_usd': safe_float(best.get('fdv')),
            'liquidity_usd': safe_float((best.get('liquidity') or {}).get('usd')),
            'volume24_usd': safe_float((best.get('volume') or {}).get('h24')),
        }
        # Debug anomaly for USDC expected ~1
        if token_address == 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v' and (metrics['price_usd'] < 0.8 or metrics['price_usd'] > 1.2):
            print(f"[token_updater][warn] USDC price anomaly stored={metrics['price_usd']} raw_pairs={len(pairs)}")
        return metrics
    except Exception as e:
        print('[token_updater] dexscreener fetch error', e)
        return None


def _updater_loop(db: AccountsDBTools):
    token_address = os.getenv(TOKEN_ADDRESS_ENV, '')
    if not token_address:
        print('[token_updater] No SPL_TOKEN_MINT set; updater disabled.')
        return
    while True:
        metrics = get_dexscreener_data(token_address)
        if metrics and metrics.get('price_usd'):
            p = metrics['price_usd']
            # Stablecoin guard for USDC
            if token_address == 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v' and (p < 0.8 or p > 1.2):
                print(f"[token_updater][skip] Ignoring anomalous USDC price {p}")
            else:
                try:
                    db.upsert_token_metrics(token_address, metrics)
                    print(f"[token_updater] Updated metrics price={metrics['price_usd']}")
                except Exception as e:
                    print('[token_updater] Failed to upsert metrics', e)
        else:
            print('[token_updater] Metrics unavailable this cycle')
        time.sleep(UPDATE_INTERVAL)


def start_background_updater():
    """Start background thread that periodically refreshes token metrics.

    Safe to call multiple times (subsequent calls are ignored once started).
    """
    # Use attribute sentinel on function to avoid duplicate threads
    if getattr(start_background_updater, '_started', False):  # type: ignore[attr-defined]
        return None
    try:
        db = AccountsDBTools(
            user_db=os.getenv('USERDB'),
            password_db=os.getenv('PASSWORDDB'),
            host_db=os.getenv('DBHOST'),
            port_db=os.getenv('PORTDB'),
            database='strawberry_platform'
        )
    except Exception as e:
        print('[token_updater] Skipping start (DB init failed):', e)
        return None
    t = threading.Thread(target=_updater_loop, args=(db,), daemon=True)
    t.start()
    start_background_updater._started = True  # type: ignore[attr-defined]
    return t


if __name__ == '__main__':  # Manual smoke run
    start_background_updater()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print('Exiting updater loop.')
