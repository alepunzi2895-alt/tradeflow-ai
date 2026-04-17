"""
TradeFlow AI — Key Levels Agent
════════════════════════════════════════════════════════════
Detects support, resistance, and liquidity areas from OHLC price action.
Used by the Risk Guardian / place_order to:
  - Snap TP just before strong levels in the path (avoid rejection)
  - Move SL beyond liquidity clusters (avoid stop hunt sweeps)
  - Return partial close targets at intermediate levels

Level Types (by priority):
  prev_session    — previous session H/L (Asian/London/NY): strength 1.0
  liquidity_pool  — equal highs/lows clusters (stop hunt zones): 0.6-0.95
  swing_high/low  — N-bar pivot points: 0.7-0.9
  order_block     — last OB candle before an impulse move: 0.7-0.9
  round_number    — $50 psychological multiples for XAU: 0.6

Timeframe strength weights (applied as multiplier to all level strengths):
  D1:  1.00  — massima autorità
  H4:  0.90  — alta importanza
  H1:  0.70  — media importanza
  M30: 0.55  — bassa importanza
  M15: 0.40
  M5:  0.25

Strength composite: base type weight × TF weight + recency bonus + touch count bonus
════════════════════════════════════════════════════════════
"""
import logging

log = logging.getLogger('tf-bot')

# Timeframe strength multipliers — higher TF = more authoritative level
TF_STRENGTH_MULT = {
    "D1":  1.00,
    "H4":  0.90,
    "H1":  0.70,
    "M30": 0.55,
    "M15": 0.40,
    "M5":  0.25,
}

# Proximity tolerance: levels within (ATR × this) are merged into one
CLUSTER_ATR_FRAC = 0.30

# Bars on each side needed to confirm a swing high/low
SWING_N = 5

# Minimum equal-H/L touches to constitute a liquidity pool
LIQUIDITY_MIN_TOUCHES = 2

# Max bars to scan backwards
MAX_SCAN_BARS = 200

# Minimum TP distance preserved after snapping (ATR multiples)
MIN_TP_ATR = 0.80


# ── LEVEL DETECTORS ────────────────────────────────────────────────────────────

def _round_number_levels(price: float, atr: float) -> list:
    step = 50.0
    base = round(price / step) * step
    levels = []
    for k in range(-8, 9):
        p = base + k * step
        if abs(p - price) <= atr * 10:
            levels.append({"price": round(p, 2), "type": "round_number",
                            "strength": 0.60, "touches": 1})
    return levels


def _find_swing_highs(H, i: int, lookback: int) -> list:
    levels = []
    start = max(SWING_N, i - lookback)
    end = i - SWING_N
    for j in range(start, end):
        if H[j] is None:
            continue
        left  = all((H[k] or 0) < H[j] for k in range(max(0,j-SWING_N), j))
        right = all((H[k] or 0) < H[j] for k in range(j+1, min(len(H), j+SWING_N+1)))
        if left and right:
            recency = 1.0 - (i - j) / max(lookback, 1)
            levels.append({
                "price": round(H[j], 2),
                "type": "swing_high",
                "strength": round(0.65 + recency * 0.25, 3),
                "touches": 1,
                "bar_idx": j,
            })
    return levels


def _find_swing_lows(L, i: int, lookback: int) -> list:
    levels = []
    start = max(SWING_N, i - lookback)
    end = i - SWING_N
    for j in range(start, end):
        if L[j] is None:
            continue
        left  = all((L[k] or float('inf')) > L[j] for k in range(max(0,j-SWING_N), j))
        right = all((L[k] or float('inf')) > L[j] for k in range(j+1, min(len(L), j+SWING_N+1)))
        if left and right:
            recency = 1.0 - (i - j) / max(lookback, 1)
            levels.append({
                "price": round(L[j], 2),
                "type": "swing_low",
                "strength": round(0.65 + recency * 0.25, 3),
                "touches": 1,
                "bar_idx": j,
            })
    return levels


def _find_liquidity_pools(H, L, i: int, lookback: int, atr: float) -> list:
    """Equal highs (sell-stop clusters) and equal lows (buy-stop clusters)."""
    tol = atr * CLUSTER_ATR_FRAC
    pools = []
    start = max(0, i - lookback)

    def cluster_prices(prices):
        used = set()
        result = []
        for a, (j, p) in enumerate(prices):
            if a in used:
                continue
            group = [(j, p)]
            group_idx = [a]
            for b, (k, q) in enumerate(prices):
                if b != a and b not in used and abs(q - p) <= tol:
                    group.append((k, q))
                    group_idx.append(b)
            if len(group) >= LIQUIDITY_MIN_TOUCHES:
                avg_p = sum(x[1] for x in group) / len(group)
                last_bar = max(x[0] for x in group)
                recency = 1.0 - (i - last_bar) / max(lookback, 1)
                strength = min(0.60 + len(group) * 0.08 + recency * 0.12, 0.95)
                result.append({
                    "price": round(avg_p, 2),
                    "type": "liquidity_pool",
                    "strength": round(strength, 3),
                    "touches": len(group),
                })
                used.update(group_idx)
        return result

    highs = [(j, H[j]) for j in range(start, i) if H[j] is not None]
    lows  = [(j, L[j]) for j in range(start, i) if L[j] is not None]
    pools += cluster_prices(highs)
    pools += cluster_prices(lows)
    return pools


def _find_order_blocks(O, H, L, C, i: int, lookback: int) -> list:
    """
    Bearish OB (resistance): last bearish candle before a strong up impulse.
    Bullish OB (support): last bullish candle before a strong down impulse.
    """
    blocks = []
    start = max(1, i - lookback)
    for j in range(start, i - 2):
        if any(x is None for x in [O[j], H[j], L[j], C[j], O[j+1], C[j+1]]):
            continue
        candle_range = H[j] - L[j]
        if candle_range <= 0:
            continue
        next_move = abs(C[j+1] - O[j+1])

        # Bearish OB → resistance zone (down candle before strong up)
        if C[j] < O[j] and next_move > candle_range * 1.5 and C[j+1] > O[j+1]:
            blocks.append({
                "price": round((H[j] + O[j]) / 2, 2),
                "zone_high": round(H[j], 2),
                "zone_low":  round(O[j], 2),
                "type": "order_block",
                "direction": "bearish",
                "strength": 0.80,
                "touches": 1,
            })

        # Bullish OB → support zone (up candle before strong down)
        elif C[j] > O[j] and next_move > candle_range * 1.5 and C[j+1] < O[j+1]:
            blocks.append({
                "price": round((L[j] + O[j]) / 2, 2),
                "zone_high": round(O[j], 2),
                "zone_low":  round(L[j], 2),
                "type": "order_block",
                "direction": "bullish",
                "strength": 0.80,
                "touches": 1,
            })
    return blocks


def _find_session_levels(candles: list, i: int) -> list:
    """Previous session H/L (Asian 00-07, London 07-13, NY 13-22) UTC."""
    levels = []
    if not candles or i < 10:
        return levels
    try:
        import datetime
        sessions = {"asian": (0, 7), "london": (7, 13), "ny": (13, 22)}
        session_data = {}
        for j in range(max(0, i - 120), i):
            c = candles[j]
            dt = c.get('dt') or c.get('t')
            if dt is None:
                continue
            if isinstance(dt, (int, float)):
                dt = datetime.datetime.utcfromtimestamp(dt)
            date = dt.date()
            for name, (h0, h1) in sessions.items():
                if h0 <= dt.hour < h1:
                    key = (date, name)
                    if key not in session_data:
                        session_data[key] = {"high": c['h'], "low": c['l']}
                    else:
                        session_data[key]["high"] = max(session_data[key]["high"], c['h'])
                        session_data[key]["low"]  = min(session_data[key]["low"],  c['l'])
                    break
        for key in sorted(session_data.keys(), reverse=True)[:4]:
            d = session_data[key]
            levels += [
                {"price": round(d["high"], 2), "type": "prev_session",
                 "session": key[1], "strength": 1.0, "touches": 1},
                {"price": round(d["low"],  2), "type": "prev_session",
                 "session": key[1], "strength": 1.0, "touches": 1},
            ]
    except Exception as e:
        log.debug(f"[KeyLevels] session detection skipped: {e}")
    return levels


# ── MERGE & SCORE ──────────────────────────────────────────────────────────────

def _merge(levels: list, atr: float) -> list:
    """Merge levels within CLUSTER_ATR_FRAC × ATR into single stronger level."""
    tol = atr * CLUSTER_ATR_FRAC
    merged = []
    used = set()
    by_strength = sorted(enumerate(levels), key=lambda x: -x[1]["strength"])

    for a, lvl in by_strength:
        if a in used:
            continue
        cluster = [lvl]
        for b, other in by_strength:
            if b != a and b not in used and abs(other["price"] - lvl["price"]) <= tol:
                cluster.append(other)
                used.add(b)
        used.add(a)

        best = max(cluster, key=lambda x: x["strength"])
        total_touches = sum(c.get("touches", 1) for c in cluster)
        merged_strength = min(best["strength"] + (total_touches - 1) * 0.04, 1.0)
        merged.append({
            "price":    best["price"],
            "type":     best["type"],
            "strength": round(merged_strength, 3),
            "touches":  total_touches,
        })

    return sorted(merged, key=lambda x: x["price"])


# ── MAIN AGENT CLASS ───────────────────────────────────────────────────────────

class KeyLevelsAgent:
    """
    Detects key price levels (S/R, liquidity, session H/L, OBs).
    Provides TP/SL adjustment and partial close targets.

    USAGE (from mt5-bot.py):
        kla = get_key_levels_agent()
        levels_result = kla.get_levels(I, i, candles=candles_h1)
        adjusted = kla.adjust_tp_sl(levels_result, entry_price, direction,
                                    tp_price, sl_price, atr)
        # adjusted['tp_price'], adjusted['sl_price'], adjusted['partial_targets']
    """

    def __init__(self, swing_lookback: int = 120):
        self.swing_lookback = swing_lookback

    def get_levels(self, I: dict, i: int,
                   candles: list = None,
                   atr: float = None,
                   tf: str = "H1") -> dict:
        """
        Compute all key levels at bar index i for a single timeframe.

        Args:
            I: indicator dict with keys H, L, O, C (from compute_indicators)
            i: current bar index
            candles: raw candle list for session H/L detection (optional)
            atr: override ATR value (defaults to I['atr'][i])
            tf: timeframe label ('D1','H4','H1','M30','M15','M5') — controls
                strength weight applied to all detected levels

        Returns:
            {levels, resistance, support, current_price, atr}
        """
        H, L, O, C = I['H'], I['L'], I['O'], I['C']
        current_price = C[i]
        if atr is None:
            atr = (I['atr'][i] or 10.0)

        lookback = min(self.swing_lookback, i - 1)
        if lookback < SWING_N * 2:
            return {"levels": [], "resistance": [], "support": [],
                    "current_price": current_price, "atr": atr}

        tf_mult = TF_STRENGTH_MULT.get(tf, 0.70)

        all_levels = []
        all_levels += _find_swing_highs(H, i, lookback)
        all_levels += _find_swing_lows(L, i, lookback)
        all_levels += _find_liquidity_pools(H, L, i, lookback, atr)
        all_levels += _find_order_blocks(O, H, L, C, i, lookback)
        all_levels += _round_number_levels(current_price, atr)
        if candles:
            all_levels += _find_session_levels(candles, i)

        # Apply TF weight multiplier to all level strengths
        for lvl in all_levels:
            lvl["strength"] = round(min(lvl["strength"] * tf_mult, 1.0), 3)
            lvl["tf"] = tf

        merged = _merge(all_levels, atr)

        gap = atr * 0.1
        resistance = sorted(
            [l for l in merged if l["price"] > current_price + gap],
            key=lambda x: x["price"]
        )
        support = sorted(
            [l for l in merged if l["price"] < current_price - gap],
            key=lambda x: -x["price"]
        )

        log.debug(
            f"[KeyLevels/{tf}] {len(merged)} levels "
            f"({len(resistance)} res, {len(support)} sup) "
            f"@ {current_price:.2f} ATR={atr:.2f} weight={tf_mult}"
        )

        return {
            "levels":        merged,
            "resistance":    resistance,
            "support":       support,
            "current_price": current_price,
            "atr":           atr,
        }

    def get_multi_tf_levels(self, tf_inputs: list, atr: float = None) -> dict:
        """
        Compute and merge key levels from multiple timeframes.
        D1/H4 levels dominate; H1 is secondary; M30 and below are tertiary.

        Args:
            tf_inputs: list of dicts, each:
                {
                  "tf":      "D1" | "H4" | "H1" | "M30" | "M15" | "M5",
                  "I":       indicator dict from compute_indicators(),
                  "i":       current bar index (use len(candles)-2),
                  "candles": raw candle list (optional, for session H/L)
                }
            atr: reference ATR for merging tolerance (uses H1 ATR if None)

        Returns:
            {levels, resistance, support, current_price, atr, tf_summary}
        """
        all_raw = []
        current_price = None
        ref_atr = atr

        for inp in tf_inputs:
            tf_name = inp["tf"]
            I       = inp["I"]
            i       = inp["i"]
            candles = inp.get("candles")

            if I is None or i is None or i < SWING_N * 2:
                continue

            tf_atr = I['atr'][i] if I['atr'][i] else 10.0
            if ref_atr is None and tf_name == "H1":
                ref_atr = tf_atr

            result = self.get_levels(I, i, candles=candles, atr=tf_atr, tf=tf_name)
            all_raw += result["levels"]

            if current_price is None and tf_name in ("H1", "M30", "H4"):
                current_price = result["current_price"]

        if ref_atr is None:
            ref_atr = 10.0
        if current_price is None and all_raw:
            current_price = all_raw[0]["price"]

        merged = _merge(all_raw, ref_atr)

        gap = ref_atr * 0.1
        resistance = sorted(
            [l for l in merged if l["price"] > current_price + gap],
            key=lambda x: x["price"]
        )
        support = sorted(
            [l for l in merged if l["price"] < current_price - gap],
            key=lambda x: -x["price"]
        )

        tf_counts = {}
        for inp in tf_inputs:
            tf_counts[inp["tf"]] = sum(1 for l in merged if l.get("tf") == inp["tf"])

        log.info(
            f"[KeyLevels] Multi-TF merge: {len(merged)} levels total "
            f"({len(resistance)} res, {len(support)} sup) | "
            + " ".join(f"{k}:{v}" for k, v in tf_counts.items())
        )

        return {
            "levels":        merged,
            "resistance":    resistance,
            "support":       support,
            "current_price": current_price,
            "atr":           ref_atr,
            "tf_summary":    tf_counts,
        }

    def adjust_tp_sl(self,
                     levels_result: dict,
                     entry_price: float,
                     direction: str,
                     tp_price: float,
                     sl_price: float,
                     atr: float) -> dict:
        """
        Adjust TP/SL based on key levels.

        TP adjustment: if a strong level (strength ≥ 0.65) lies between entry
          and TP, snap TP to just before it to avoid rejection.
          Minimum TP distance preserved: MIN_TP_ATR × ATR.

        SL adjustment: if a liquidity pool lies between SL and entry,
          move SL just beyond it so a stop hunt sweep doesn't trigger it.

        Args:
            levels_result: output of get_levels()
            entry_price: order fill price (ask for buy, bid for sell)
            direction: 'buy' | 'sell'
            tp_price: raw TP price
            sl_price: raw SL price
            atr: current ATR

        Returns:
            {tp_price, sl_price, tp_adjusted, sl_adjusted,
             partial_targets, notes}
        """
        notes = []
        tp_adj = False
        sl_adj = False
        partial_targets = []
        min_tp_dist = atr * MIN_TP_ATR

        if direction == 'buy':
            # ── TP: snap before nearest blocking resistance ─────────────────
            blocking = [
                l for l in levels_result.get("resistance", [])
                if entry_price < l["price"] <= tp_price and l["strength"] >= 0.65
            ]
            if blocking:
                nearest = blocking[0]
                new_tp = round(nearest["price"] - atr * 0.15, 2)
                if new_tp - entry_price >= min_tp_dist:
                    notes.append(
                        f"TP {tp_price:.2f}→{new_tp:.2f} "
                        f"({nearest['type']} @{nearest['price']:.2f} str={nearest['strength']:.2f})"
                    )
                    tp_price = new_tp
                    tp_adj = True

            # ── SL: move below liquidity cluster to avoid sweep ─────────────
            liq_below = [
                l for l in levels_result.get("support", [])
                if sl_price < l["price"] < entry_price
                and l["type"] == "liquidity_pool"
            ]
            if liq_below:
                pool = liq_below[0]  # closest to current price
                new_sl = round(pool["price"] - atr * 0.20, 2)
                if entry_price - new_sl >= min_tp_dist * 0.5:
                    notes.append(
                        f"SL {sl_price:.2f}→{new_sl:.2f} "
                        f"(liquidity pool @{pool['price']:.2f} str={pool['strength']:.2f})"
                    )
                    sl_price = new_sl
                    sl_adj = True

            # ── Partial targets: strong levels between entry and TP ─────────
            partial_targets = [
                {"price": l["price"], "type": l["type"], "strength": l["strength"]}
                for l in levels_result.get("resistance", [])
                if entry_price < l["price"] <= tp_price and l["strength"] >= 0.65
            ]

        else:  # sell
            # ── TP: snap before nearest blocking support ────────────────────
            blocking = [
                l for l in levels_result.get("support", [])
                if tp_price <= l["price"] < entry_price and l["strength"] >= 0.65
            ]
            if blocking:
                nearest = blocking[0]  # highest support = closest to entry
                new_tp = round(nearest["price"] + atr * 0.15, 2)
                if entry_price - new_tp >= min_tp_dist:
                    notes.append(
                        f"TP {tp_price:.2f}→{new_tp:.2f} "
                        f"({nearest['type']} @{nearest['price']:.2f} str={nearest['strength']:.2f})"
                    )
                    tp_price = new_tp
                    tp_adj = True

            # ── SL: move above liquidity cluster ───────────────────────────
            liq_above = [
                l for l in levels_result.get("resistance", [])
                if entry_price < l["price"] < sl_price
                and l["type"] == "liquidity_pool"
            ]
            if liq_above:
                pool = liq_above[-1]  # closest to entry
                new_sl = round(pool["price"] + atr * 0.20, 2)
                if new_sl - entry_price >= min_tp_dist * 0.5:
                    notes.append(
                        f"SL {sl_price:.2f}→{new_sl:.2f} "
                        f"(liquidity pool @{pool['price']:.2f} str={pool['strength']:.2f})"
                    )
                    sl_price = new_sl
                    sl_adj = True

            partial_targets = [
                {"price": l["price"], "type": l["type"], "strength": l["strength"]}
                for l in levels_result.get("support", [])
                if tp_price <= l["price"] < entry_price and l["strength"] >= 0.65
            ]

        if notes:
            log.info(f"[KeyLevels] {direction.upper()} adjustments: {' | '.join(notes)}")

        return {
            "tp_price":       tp_price,
            "sl_price":       sl_price,
            "tp_adjusted":    tp_adj,
            "sl_adjusted":    sl_adj,
            "partial_targets": partial_targets,
            "notes":          notes,
        }


# ── SINGLETON ──────────────────────────────────────────────────────────────────
_kl_instance: KeyLevelsAgent = None


def get_key_levels_agent(swing_lookback: int = 120) -> KeyLevelsAgent:
    global _kl_instance
    if _kl_instance is None:
        _kl_instance = KeyLevelsAgent(swing_lookback=swing_lookback)
    return _kl_instance
