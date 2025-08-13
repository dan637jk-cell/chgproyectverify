import requests, os, time, json, threading, statistics
from typing import Optional, Dict, Any, List

_price_cache_lock = threading.Lock()
_price_cache: Dict[str, Any] = {
    # token_address: { 'price': float, 'ts': epoch_seconds, 'raw': {...} }
}

def _pick_highest_liquidity_pair(pairs):
    """Return pair dict with highest liquidity.usd (float) or None."""
    best = None
    best_liq = -1.0
    for p in pairs or []:
        try:
            liq = float(((p or {}).get('liquidity') or {}).get('usd') or 0)
        except Exception:
            liq = 0.0
        if liq > best_liq:
            best_liq = liq
            best = p
    return best

STABLE_MINTS = {
    # Solana USDC
    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': {'symbol': 'USDC', 'expected': 1.0, 'range': (0.8, 1.2)},
    # (Add other stable mints here if needed)
}

def _extract_prices(pairs: List[dict]) -> List[float]:
    prices = []
    for p in pairs:
        try:
            v = p.get('priceUsd')
            if v is None:
                continue
            prices.append(float(v))
        except Exception:
            continue
    return prices

def get_dexscreener_price(token_address: str, chain: str = "solana") -> Optional[float]:
    """Return a robust priceUsd for token:
    - Fetch all pairs
    - For stable mints: filter outliers outside expected range; use median of remaining
    - For non-stable: choose highest-liquidity pair price; fallback to median if that looks anomalous
    - Adds debug when anomalous (<1e-6 or huge deviations)
    """
    if not token_address:
        return None
    url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
    try:
        r = requests.get(url, timeout=15)
    except Exception as e:
        print(f"[price] request error: {e}")
        return None
    if r.status_code != 200:
        print(f"[price] non-200 status {r.status_code}")
        return None
    try:
        data = r.json()
    except Exception as e:
        print(f"[price] JSON parse error: {e}")
        return None
    if not isinstance(data, dict):
        return None
    pairs = [p for p in (data.get('pairs') or []) if isinstance(p, dict) and p.get('chainId') == chain]
    if not pairs:
        return None

    stable_cfg = STABLE_MINTS.get(token_address)
    prices = _extract_prices(pairs)
    if not prices:
        return None

    if stable_cfg:
        lo, hi = stable_cfg['range']
        filtered = [p for p in prices if lo <= p <= hi]
        source_list = filtered if filtered else prices
        try:
            med = statistics.median(source_list)
        except Exception:
            med = source_list[0]
        if med < lo or med > hi:
            print(f"[price][warn] stable coin median out of expected range token={stable_cfg['symbol']} median={med}")
        return med

    # Non-stable path
    best = _pick_highest_liquidity_pair(pairs)
    best_price = None
    try:
        if best:
            best_price = float(best.get('priceUsd'))
    except Exception:
        best_price = None
    if best_price is None:
        return prices[0]
    # If best_price is extreme outlier vs median (factor 10x), fallback to median
    try:
        med_all = statistics.median(prices)
        if med_all > 0 and (best_price/med_all > 10 or med_all/best_price > 10):
            print(f"[price][warn] outlier price detected best={best_price} median={med_all} -> using median")
            return med_all
    except Exception:
        pass
    return best_price

def get_token_price_cached(token_address: str, ttl: int = 60) -> Optional[float]:
    """Return cached price (refresh if older than ttl seconds)."""
    now = time.time()
    with _price_cache_lock:
        rec = _price_cache.get(token_address)
        if rec and (now - rec['ts']) < ttl:
            return rec['price']
    # fetch fresh outside lock to avoid long hold
    price = get_dexscreener_price(token_address)
    if price is None:
        return None
    with _price_cache_lock:
        _price_cache[token_address] = {'price': price, 'ts': now}
    return price

def update_price_in_background(token_address: str, filepath: str, interval: int = 360):
    while True:
        price = get_dexscreener_price(token_address)
        if price:
            try:
                with open(filepath, 'w') as f:
                    json.dump({'price_usd': price, 'ts': time.time()}, f)
            except Exception as e:
                print(f"[price-bg] failed writing cache file: {e}")
        time.sleep(interval)
