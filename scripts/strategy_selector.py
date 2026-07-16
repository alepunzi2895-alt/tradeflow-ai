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
            # bt_h1_adaptive 2026-07-07: 1070 trade, WR 48.9%, PF 1.594, +$3896/24m, DD$264 — BEST TF
            # bt_h4_adaptive 2026-07-07: 208 trade, WR 52.4%, PF 1.835, +$992/24m (meno segnali)
            # bt_m30_adaptive 2026-07-07: 575 trade, WR 43.8%, PF 1.300, +$1164/13m
            "H1":  {"wr": 0.489, "pf": 1.594, "daily_pnl": 17.4, "dd": 264},
            "H4":  {"wr": 0.524, "pf": 1.835, "daily_pnl": 10.9, "dd": 124},
            "M30": {"wr": 0.438, "pf": 1.300, "daily_pnl": 8.0,  "dd": 244},
        },
        "optimal_regimes": ["TREND_UP", "TREND_DOWN", "WEAK"],
        "base_params": {"tp_atr_mult": 3.5, "sl_atr_mult": 1.0},
    },
    {
        "id": "S09_MFKK_SCALPING",
        "name": "MFKK Scalping",
        "signal_function": "signal_mfkk_scalping",
        "performance_by_tf": {
            # bt_m30_adaptive 2026-07-07: 12 trade, WR 25.0%, PF 1.782, +$63/13m — BEST TF
            # bt_h1_adaptive 2026-07-07: 17 trade, WR 35.3%, PF 1.311, +$38/24m
            # Solo in adaptive (regime-gated). Standalone ≈ 0% WR su tutti i TF.
            "M30": {"wr": 0.250, "pf": 1.782, "daily_pnl": 0.5, "dd": 40},
            "H1":  {"wr": 0.353, "pf": 1.311, "daily_pnl": 0.3, "dd": 71},
        },
        "optimal_regimes": ["VOLATILE", "WEAK"],
        "base_params": {"tp_atr_mult": 4.0, "sl_atr_mult": 1.5},
    },
    {
        "id": "S10_OB_FVG_SCALP",
        "name": "OB+FVG Scalp",
        "signal_function": "signal_ob_fvg_scalp",
        "performance_by_tf": {
            # bt_m30_adaptive 2026-07-07: 11 trade, WR 54.5%, PF 1.949, +$208/13m — campione piccolo
            # bt_h1_adaptive 2026-07-07: 4 trade WR 0%, P&L negativo — non usare H1
            "M30": {"wr": 0.545, "pf": 1.949, "daily_pnl": 2.0, "dd": 154},
            "H1":  {"wr": 0.050, "pf": 0.300, "daily_pnl": -1.0, "dd": 200},
        },
        "optimal_regimes": ["RANGING", "VOLATILE"],
        "session_filter": ["london", "overlap"],
        "min_confidence": 0.75,
        "base_params": {"tp_atr_mult": 3.5, "sl_atr_mult": 1.5},
    },
    {
        "id": "S16_GOLDEN_SQUEEZE",
        "name": "Elite Golden Squeeze",
        "signal_function": "signal_golden_squeeze",
        "performance_by_tf": {
            # bt_h1_adaptive 2026-07-07: 245 trade, WR 48.6%, PF 1.770, +$2165/24m, DD$402 — BEST TF
            # bt_m30_adaptive 2026-07-07: PF 0.787 (negativo) — non usare M30
            "H1":  {"wr": 0.486, "pf": 1.770, "daily_pnl": 18.3, "dd": 402},
            "M30": {"wr": 0.364, "pf": 0.787, "daily_pnl": -6.4, "dd": 894},
        },
        "optimal_regimes": ["TREND_UP", "TREND_DOWN", "WEAK"],
        "session_filter": ["london", "overlap", "ny"],
        "base_params": {"tp_atr_mult": 3.5, "sl_atr_mult": 2.0},
    },
    {
        "id": "S17_CONVERGENCE_SCALP",
        "name": "Convergence Scalp",
        "signal_function": "signal_convergence_scalp",
        "performance_by_tf": {
            # bt_h4_adaptive 2026-07-07: 95 trade, WR 35.8%, PF 2.709, +$2819/24m, DD$198 — BEST TF
            # bt_h1_adaptive: standalone PF 0.004 (pessimo) — non usare H1 standalone
            # bt_m30_adaptive: standalone PF 0.049 (pessimo) — non usare M30
            "H4":  {"wr": 0.358, "pf": 2.709, "daily_pnl": 32.0, "dd": 198},
            "H1":  {"wr": 0.050, "pf": 0.500, "daily_pnl": -1.0, "dd": 400},
            "M30": {"wr": 0.030, "pf": 0.300, "daily_pnl": -1.5, "dd": 350},
        },
        "optimal_regimes": ["VOLATILE", "TREND_UP", "TREND_DOWN"],
        "min_atr_percentile": 0.60,
        "base_params": {"tp_atr_mult": 4.0, "sl_atr_mult": 1.1},
    },
    {
        "id": "S18_RANGE_REVERSAL",
        "name": "Range Reversal BB",
        "signal_function": "signal_range_reversal",
        "performance_by_tf": {
            # bt_m30_adaptive 2026-07-07: 92 trade, WR 43.5%, PF 1.061, +$42/13m (regime-gated)
            # bt_m5_adaptive: WR 45.4%, PF 1.438, +$648/13m — M5 teoricamente migliore ma bot usa M30
            # bt_h1_adaptive: PF 0.755 standalone (negativo senza regime) — non usare H1
            "M30": {"wr": 0.435, "pf": 1.061, "daily_pnl": 0.3, "dd": 170},
        },
        "optimal_regimes": ["RANGING", "WEAK"],
        "base_params": {"tp_atr_mult": 2.0, "sl_atr_mult": 1.2},
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
    if score_mult == 0.0:
        # Hard block: strategia bloccata dal PerformanceTracker → score 0, non viene selezionata
        score = 0.0
    else:
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
