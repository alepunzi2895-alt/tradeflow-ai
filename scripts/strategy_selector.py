"""
TradeFlow AI — Strategy Selector Agent
═══════════════════════════════════════════════════════════════════
Selects the optimal strategy + timeframe based on market regime scoring.

USAGE:
  from strategy_selector import StrategySelector
  sel = StrategySelector()
  result = sel.select(I, i, hour_utc, current_strategy_id)
  # result = {"strategy_id": ..., "timeframe": ..., "confidence": ..., "reasoning": ...}
═══════════════════════════════════════════════════════════════════
"""
import datetime
import json
import logging
import os

log = logging.getLogger('tf-bot')

# ── STRATEGY REGISTRY ─────────────────────────────────────────────────────────
# Backtest results from canonical campaigns. Update as new backtests run.
STRATEGIES_CONFIG = [
    {
        "id": "S00_MFKK",
        "name": "MFKK Score",
        "signal_function": "signal_mfkk_score",
        "performance_by_tf": {
            # M30 adaptive V2 (2026-04-28): WR 26.1%, PF 1.240 (DI≥20 or ST bullish gate, sell London/NY only)
            # H4 adaptive: 618 trade, WR 44.2%, +$1320 / 25 months (best standalone)
            "M30": {"wr": 0.261, "pf": 1.240, "daily_pnl": 2.2, "dd": 220},
            "H4":  {"wr": 0.442, "pf": 1.319, "daily_pnl": 3.43, "dd": 400},
        },
        "optimal_regimes": ["TREND_UP", "TREND_DOWN", "WEAK"],
        "base_params": {"tp_atr_mult": 3.5, "sl_atr_mult": 1.0},
    },
    {
        "id": "S05_MFKK_INTRADAY",
        "name": "MFKK Intraday",
        "signal_function": "signal_mfkk_intraday",
        "performance_by_tf": {
            # H1 adaptive V4 (2026-04-28): 197 trade, WR 23.4%, session+ST+ATR filter. Marginal on H1.
            # H4 adaptive V4 (2026-04-28): 29 trade, WR 34.5%, +$769 — best TF for this strategy.
            "H1":  {"wr": 0.234, "pf": 1.070, "daily_pnl": 0.1, "dd": 180},
            "H4":  {"wr": 0.345, "pf": 1.300, "daily_pnl": 3.3, "dd": 200},
            "M30": {"wr": 0.262, "pf": 1.050, "daily_pnl": 0.1, "dd": 300},
        },
        "optimal_regimes": ["TREND_UP", "TREND_DOWN"],
        "base_params": {"tp_atr_mult": 3.5, "sl_atr_mult": 1.0},
    },
    {
        "id": "S09_MFKK_SCALPING",
        "name": "MFKK Scalping",
        "signal_function": "signal_mfkk_scalping",
        "performance_by_tf": {
            # M30 adaptive V3 (2026-04-28): 202 trade, WR 29.2%, session 06-19h + ST filter
            # H1 adaptive V3 (2026-04-28): 83 trade, WR 25.3%, +$379 — positive on H1 too
            "M30": {"wr": 0.292, "pf": 1.400, "daily_pnl": 1.5, "dd": 150},
            "H1":  {"wr": 0.253, "pf": 1.200, "daily_pnl": 0.5, "dd": 200},
        },
        "optimal_regimes": ["VOLATILE", "WEAK"],
        "base_params": {"tp_atr_mult": 4.0, "sl_atr_mult": 1.0},
    },
    {
        "id": "S10_OB_FVG_SCALP",
        "name": "OB+FVG Scalp",
        "signal_function": "signal_ob_fvg_scalp",
        "performance_by_tf": {
            # M30 adaptive V3 (2026-04-28): 49 trade, WR 51.0%, ADX≥18 + ST filter — high quality
            # H1 adaptive V3 (2026-04-28): 58 trade, WR 31.0%, +$5 — neutral
            "M30": {"wr": 0.510, "pf": 1.800, "daily_pnl": 1.1, "dd": 120},
            "H1":  {"wr": 0.310, "pf": 1.200, "daily_pnl": 0.1, "dd": 200},
        },
        "optimal_regimes": ["RANGING", "WEAK"],
        "min_confidence": 0.70,
        "base_params": {"tp_atr_mult": 3.5, "sl_atr_mult": 1.2},
    },
    {
        "id": "S16_GOLDEN_SQUEEZE",
        "name": "Elite Golden Squeeze",
        "signal_function": "signal_golden_squeeze",
        "performance_by_tf": {
            # Sistema adattivo H1 V4 (2026-04-28): WR 45.0%, PF 1.380 (H4 context filter SELL)
            # BUY WR 44.5%, SELL WR 50% (countertrend only). H4 bearish SELL blocked.
            "H1":  {"wr": 0.450, "pf": 1.380, "daily_pnl": 1.8, "dd": 300},
            "M30": {"wr": 0.397, "pf": 1.150, "daily_pnl": 2.88, "dd": 1100},
        },
        "optimal_regimes": ["TREND_UP", "TREND_DOWN"],
        "session_filter": ["london", "ny"],
        "base_params": {"tp_atr_mult": 3.5, "sl_atr_mult": 2.0},
    },
    {
        "id": "S17_CONVERGENCE_SCALP",
        "name": "Convergence Scalp",
        "signal_function": "signal_convergence_scalp",
        "performance_by_tf": {
            # H4 adaptive (2026-04-28): 119 trade, WR 35.3%, +$3052 / 23 months — BEST TF
            # H1 adaptive: 75 trade, WR 28.0%, +$521 — good secondary
            # M30 adaptive: 156 trade, WR 24.4%, +$131
            "H4":  {"wr": 0.353, "pf": 1.750, "daily_pnl": 4.4, "dd": 250},
            "H1":  {"wr": 0.280, "pf": 1.300, "daily_pnl": 0.7, "dd": 400},
            "M30": {"wr": 0.244, "pf": 1.100, "daily_pnl": 0.3, "dd": 300},
        },
        "optimal_regimes": ["VOLATILE", "TREND_UP", "TREND_DOWN"],
        "min_atr_percentile": 0.60,
        "base_params": {"tp_atr_mult": 4.0, "sl_atr_mult": 1.1},
    },
]

# Regime aliases: map internal bot regimes to canonical names
_REGIME_ALIAS = {
    "TREND_UP":   "TREND_UP",
    "TREND_DOWN": "TREND_DOWN",
    "WEAK_UP":    "WEAK",
    "WEAK_DOWN":  "WEAK",
    "VOLATILE":   "VOLATILE",
    "RANGE":      "RANGING",
    "RANGING":    "RANGING",
    "WEAK":       "WEAK",
    "UNKNOWN":    "WEAK",
    "EXTREME":    "VOLATILE",
}

# Hours UTC for session classification
_SESSION_HOURS = {
    "asian":   range(0, 7),
    "london":  range(7, 13),
    "overlap": range(13, 17),
    "ny":      range(17, 22),
}


def _get_session(hour_utc: int) -> str:
    for session, hours in _SESSION_HOURS.items():
        if hour_utc in hours:
            return session
    return "asian"


def _best_tf(strategy: dict) -> tuple:
    """Returns (tf, perf_dict) with highest pf * wr."""
    perf = strategy["performance_by_tf"]
    return max(perf.items(), key=lambda x: x[1]["pf"] * x[1]["wr"])


def detect_regime_extended(I: dict, i: int) -> dict:
    """
    Extended regime detection returning type + strength + atr_percentile.
    Extends the bot's simple detect_regime() with additional metadata.
    """
    adx = I['adx'][i]
    dip = I['dip'][i]
    dim = I['dim'][i]
    atr_v = I['atr'][i]
    atr_avg = I.get('atr_avg', [None] * (i + 1))[i]

    if adx is None:
        return {"type": "UNKNOWN", "strength": 0.3, "atr_percentile": 0.5}

    # ATR percentile vs 30-bar rolling average
    atr_ratio = (atr_v / atr_avg) if (atr_v and atr_avg and atr_avg > 0) else 1.0
    # Map ratio [0.5, 2.0] → [0.0, 1.0]
    atr_percentile = min(max((atr_ratio - 0.5) / 1.5, 0.0), 1.0)

    # Determine regime type
    if atr_v and atr_avg and atr_v > 3.0 * atr_avg:
        regime_type = "VOLATILE"
        strength = 0.9
    elif adx >= 30:
        regime_type = "TREND_UP" if dip > dim else "TREND_DOWN"
        # Strength: scale ADX 30-50 → 0.5-1.0
        strength = min(0.5 + (adx - 30) / 40, 1.0)
    elif adx >= 18:
        regime_type = "WEAK"
        strength = 0.35 + (adx - 18) / 60
    elif atr_v and atr_avg and atr_v > 1.4 * atr_avg:
        regime_type = "VOLATILE"
        strength = min(0.3 + (atr_ratio - 1.4) / 1.5, 0.9)
    elif adx < 20:
        regime_type = "RANGING"
        # Low ADX = stronger ranging
        strength = 0.5 + (20 - adx) / 40
    else:
        regime_type = "WEAK"
        strength = 0.3

    return {
        "type": regime_type,
        "strength": round(min(strength, 1.0), 3),
        "atr_percentile": round(atr_percentile, 3),
        "adx": adx,
        "dip": dip,
        "dim": dim,
    }


def _load_score_overrides() -> dict:
    """Legge data/strategy_overrides.json → {strategy_id: score_mult}. Silent on error."""
    try:
        _base = os.path.dirname(os.path.abspath(__file__))
        path  = os.path.join(_base, '..', 'data', 'strategy_overrides.json')
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        return {sid: v.get("score_mult", 1.0) for sid, v in raw.items()}
    except Exception:
        return {}


def _score_strategy(strategy: dict, regime: dict, session: str,
                    recent_wr: float = None) -> dict:
    """Score a single strategy 0-100."""
    score = 0.0
    regime_canonical = _REGIME_ALIAS.get(regime["type"], "WEAK")

    # 1. Regime match (0-40 pts)
    if regime_canonical in strategy["optimal_regimes"]:
        score += 40 * regime["strength"]

    # 2. Best TF performance (0-30 pts) — normalize PF capped at 2.0
    best_tf_name, best_tf_perf = _best_tf(strategy)
    pf_norm = min(best_tf_perf["pf"] / 2.0, 1.0)
    score += 30 * pf_norm

    # 3. Session compatibility (0-20 pts)
    session_filter = strategy.get("session_filter")
    if session_filter:
        if session in session_filter or (session == "overlap" and "ny" in session_filter):
            score += 20
        else:
            score += 5   # not blocked, just not ideal
    else:
        score += 20  # no filter = always active

    # 4. Recent performance vs 50% WR baseline (0-10 pts)
    if recent_wr is not None:
        score += 10 * min(recent_wr / 0.5, 2.0) * 0.5  # clamp
    else:
        # Use backtest WR as proxy
        score += 10 * min(best_tf_perf["wr"] / 0.5, 1.0) * 0.5

    # ATR percentile gate for convergence scalp
    if "min_atr_percentile" in strategy:
        if regime["atr_percentile"] < strategy["min_atr_percentile"]:
            score *= 0.4  # heavy penalty

    # min_confidence gate
    if "min_confidence" in strategy:
        if (score / 100.0) < strategy["min_confidence"]:
            score *= 0.5

    # ── Performance Tracker override (self-learning) ──────────────────────────
    overrides = _load_score_overrides()
    score_mult = overrides.get(strategy["id"], 1.0)
    score *= score_mult

    return {
        "strategy_id": strategy["id"],
        "name": strategy["name"],
        "timeframe": best_tf_name,
        "score": round(min(score, 100.0), 2),
        "confidence": round(min(score, 100.0) / 100.0, 3),
        "expected_daily_pnl": best_tf_perf["daily_pnl"],
        "tp_atr_mult": strategy["base_params"]["tp_atr_mult"],
        "sl_atr_mult": strategy["base_params"]["sl_atr_mult"],
    }


class StrategySelector:
    """
    Selects the best strategy+timeframe each H1/M30 bar using regime scoring.
    Includes hysteresis to avoid ping-pong switching.
    """

    # Minimum score gap required to switch away from current strategy
    MIN_SWITCH_GAP = 15
    # Score above which current strategy is "good enough" → don't switch
    STAY_THRESHOLD = 60

    def __init__(self):
        self._current_strategy_id: str = None
        self._current_score: float = 0.0
        self._last_switch_time: datetime.datetime = None

    def select(self, I: dict, i: int, hour_utc: int,
               recent_wr_map: dict = None) -> dict:
        """
        Run full selection pipeline.

        Args:
            I: indicator dict from compute_indicators()
            i: current bar index
            hour_utc: current UTC hour (for session classification)
            recent_wr_map: {strategy_id: win_rate_last_30} (optional)

        Returns:
            dict with selected_strategy, timeframe, confidence, reasoning, scores
        """
        regime = detect_regime_extended(I, i)
        session = _get_session(hour_utc)

        scores = []
        for strat in STRATEGIES_CONFIG:
            recent_wr = (recent_wr_map or {}).get(strat["id"])
            s = _score_strategy(strat, regime, session, recent_wr)
            scores.append(s)

        scores.sort(key=lambda x: x["score"], reverse=True)
        top = scores[0]

        # Hysteresis: find current strategy score
        if self._current_strategy_id:
            curr_entry = next(
                (s for s in scores if s["strategy_id"] == self._current_strategy_id),
                None
            )
            curr_score = curr_entry["score"] if curr_entry else 0.0

            if curr_score >= self.STAY_THRESHOLD:
                # Current strategy is still good enough
                selected = curr_entry
                switched = False
            elif top["score"] >= curr_score + self.MIN_SWITCH_GAP:
                selected = top
                switched = True
            else:
                selected = curr_entry or top
                switched = False
        else:
            selected = top
            switched = True

        if switched:
            self._current_strategy_id = selected["strategy_id"]
            self._current_score = selected["score"]
            self._last_switch_time = datetime.datetime.utcnow()

        alternative = scores[1] if len(scores) > 1 and scores[1]["strategy_id"] != selected["strategy_id"] else None

        reasoning = (
            f"Regime={regime['type']} (ADX={regime.get('adx', 0):.0f}, "
            f"strength={regime['strength']:.2f}, ATR%={regime['atr_percentile']:.2f}) | "
            f"Session={session} | "
            f"{selected['name']}@{selected['timeframe']} score={selected['score']:.0f}/100 "
            f"(PnL={selected['expected_daily_pnl']:+.1f}/day)"
        )

        result = {
            "selected_strategy": selected["strategy_id"],
            "timeframe": selected["timeframe"],
            "confidence": selected["confidence"],
            "score": selected["score"],
            "regime": regime,
            "session": session,
            "reasoning": reasoning,
            "alternative": alternative["strategy_id"] if alternative else None,
            "switch_occurred": switched,
            "all_scores": scores,
            "tp_atr_mult": selected["tp_atr_mult"],
            "sl_atr_mult": selected["sl_atr_mult"],
        }

        if switched:
            log.info(
                f"[StrategySelector] → {selected['strategy_id']}@{selected['timeframe']} "
                f"score={selected['score']:.0f} | {reasoning}"
            )
        else:
            log.debug(
                f"[StrategySelector] HOLD {selected['strategy_id']} "
                f"score={selected['score']:.0f} (no switch)"
            )

        return result
