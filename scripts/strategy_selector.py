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
            # M30 adaptive: 1597 trade, WR 38.3%, +$388 / 25 months (fallback role)
            # H4 adaptive: 618 trade, WR 44.2%, +$1320 / 25 months (best standalone)
            "M30": {"wr": 0.383, "pf": 1.033, "daily_pnl": 1.01, "dd": 300},
            "H4":  {"wr": 0.442, "pf": 1.319, "daily_pnl": 3.43, "dd": 400},
        },
        "optimal_regimes": ["TREND_UP", "TREND_DOWN", "WEAK"],
        "base_params": {"tp_atr_mult": 2.0, "sl_atr_mult": 1.0},
    },
    {
        "id": "S05_MFKK_INTRADAY",
        "name": "MFKK Intraday",
        "signal_function": "signal_mfkk_intraday",
        "performance_by_tf": {
            # H1 confirmed optimal: 282 trade, WR 41.5%, +$834 / 25 months
            "H1":  {"wr": 0.415, "pf": 1.361, "daily_pnl": 1.68, "dd": 800},
            "M30": {"wr": 0.369, "pf": 1.124, "daily_pnl": 0.58, "dd": 500},
        },
        "optimal_regimes": ["TREND_UP", "TREND_DOWN"],
        "base_params": {"tp_atr_mult": 2.0, "sl_atr_mult": 1.0},
    },
    {
        "id": "S09_MFKK_SCALPING",
        "name": "MFKK Scalping",
        "signal_function": "signal_mfkk_scalping",
        "performance_by_tf": {
            # M30 adaptive: 267 trade, WR 37.8%, PF 1.637 — much better than M5
            "M30": {"wr": 0.378, "pf": 1.637, "daily_pnl": 1.83, "dd": 400},
            "M5":  {"wr": 0.284, "pf": 1.143, "daily_pnl": 0.28, "dd": 200},
            "M15": {"wr": 0.245, "pf": 1.282, "daily_pnl": 0.87, "dd": 500},
        },
        "optimal_regimes": ["VOLATILE", "WEAK"],
        "base_params": {"tp_atr_mult": 3.0, "sl_atr_mult": 1.0},
    },
    {
        "id": "S10_OB_FVG_SCALP",
        "name": "OB+FVG Scalp",
        "signal_function": "signal_ob_fvg_scalp",
        "performance_by_tf": {
            # M30 adaptive: 73 trade, WR 42.5%, PF 1.796
            "M30": {"wr": 0.425, "pf": 1.796, "daily_pnl": 1.39, "dd": 300},
            "H1":  {"wr": 0.333, "pf": 1.476, "daily_pnl": 0.77, "dd": 400},
        },
        "optimal_regimes": ["RANGING", "WEAK"],
        "min_confidence": 0.70,
        "base_params": {"tp_atr_mult": 2.5, "sl_atr_mult": 1.2},
    },
    {
        "id": "S16_GOLDEN_SQUEEZE",
        "name": "Elite Golden Squeeze",
        "signal_function": "signal_golden_squeeze",
        "performance_by_tf": {
            # Backtest canonico 2026-04-19 (MT5 GOLD M30, 25 mesi): 1006 trade, WR 29.0%, PF 0.904, -$1144
            # V3 rescaled (ADX>=25, OBV 3-bar, candle 0.35xATR) — NON ancora backtestato in produzione
            "M30": {"wr": 0.290, "pf": 0.904, "daily_pnl": -1.5, "dd": 1200},
            "H1":  {"wr": 0.290, "pf": 0.900, "daily_pnl": -1.2, "dd": 1000},
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
            # H4 adaptive: 94 trade, WR 41.5%, PF 1.710 — best TF
            # H1 adaptive: 357 trade, WR 30.3%, PF 1.323 — good secondary
            "H4":  {"wr": 0.415, "pf": 1.710, "daily_pnl": 2.05, "dd": 400},
            "H1":  {"wr": 0.303, "pf": 1.323, "daily_pnl": 1.70, "dd": 700},
            "M30": {"wr": 0.257, "pf": 1.107, "daily_pnl": 0.76, "dd": 600},
            "M5":  {"wr": 0.269, "pf": 1.167, "daily_pnl": 0.86, "dd": 500},
        },
        "optimal_regimes": ["VOLATILE", "TREND_UP", "TREND_DOWN"],
        "min_atr_percentile": 0.60,
        "base_params": {"tp_atr_mult": 2.8, "sl_atr_mult": 1.1},
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
