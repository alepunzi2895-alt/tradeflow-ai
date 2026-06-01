"""
TradeFlow AI — Risk Guardian Agent
═══════════════════════════════════════════════════════════════════
Dynamic risk management based on composite confidence score.

Replaces/extends risk_manager.py with:
  - 5-tier system driven by COMPOSITE confidence (not just AI Score)
  - Composite = strategy_confidence × 0.50 + signal_quality × 0.30 + market_conditions × 0.20
  - Account health adjustments (daily loss, weekly drawdown, equity growth)
  - Full position management: BE, trailing, early exit, regime shift override
  - Gentle compounding: lot scales with sqrt(equity_ratio), capped at 3×

USAGE:
  from risk_guardian import RiskGuardian
  rg = RiskGuardian(base_lot=0.05, max_lot=0.25, initial_equity=10000.0)

  # On new signal
  params = rg.get_order_params(
      strategy_confidence=0.85,
      signal_quality=0.72,
      atr=12.5,
      strategy_id='S16_GOLDEN_SQUEEZE',
      today_pnl=-50.0,
      weekly_dd_pct=0.01,
      current_equity=10100.0,
      hour_utc=10,
  )

  # In monitoring loop (every 10s)
  actions = rg.manage_positions(mt5, symbol, magic, current_atr, current_regime)
═══════════════════════════════════════════════════════════════════
"""
import math
import time
import logging
import datetime

log = logging.getLogger('tf-bot')

# ── RISK TIER TABLE ────────────────────────────────────────────────────────────
RISK_TIERS = {
    "CONSERVATIVE": {
        "score_min": 0,   "score_max": 40,
        "lot_multiplier": 0.5,  "tp_multiplier": 1.0, "sl_multiplier": 0.8,
        "be_trigger": 0.65,     "ts_step": 1.5,       "early_exit_threshold": 0.30,
        "label": "🔵 CONSERVATIVE",
    },
    "NORMAL": {
        "score_min": 40,  "score_max": 60,
        "lot_multiplier": 1.0,  "tp_multiplier": 1.0, "sl_multiplier": 1.0,
        "be_trigger": 0.55,     "ts_step": 1.2,       "early_exit_threshold": 0.20,
        "label": "⚪ NORMAL",
    },
    "AGGRESSIVE": {
        "score_min": 60,  "score_max": 75,
        "lot_multiplier": 1.5,  "tp_multiplier": 1.5, "sl_multiplier": 1.0,
        "be_trigger": 0.45,     "ts_step": 0.9,       "early_exit_threshold": 0.10,
        "label": "🟡 AGGRESSIVE",
    },
    "STRONG": {
        "score_min": 75,  "score_max": 85,
        "lot_multiplier": 2.0,  "tp_multiplier": 1.8, "sl_multiplier": 1.2,
        "be_trigger": 0.40,     "ts_step": 0.8,       "early_exit_threshold": 0.05,
        "label": "🟠 STRONG",
    },
    "MAX": {
        "score_min": 85,  "score_max": 100,
        "lot_multiplier": 2.5,  "tp_multiplier": 2.0, "sl_multiplier": 1.5,
        "be_trigger": 0.35,     "ts_step": 0.8,       "early_exit_threshold": 0.05,
        "label": "🔴 MAX",
    },
}

STRATEGY_ATR_PARAMS = {
    # SL alzato a 1.5×ATR (era 1.0) per S05/S09/S10/S17/S00 (2026-04-30):
    # Con ATR H1 ≈12pt e range H4 ≈25-50pt, un SL di 1×ATR viene spazzato da normali
    # fluttuazioni intracandela prima che il trade si stabilisca.
    "S05_MFKK_INTRADAY":    {"tp_atr": 3.5, "sl_atr": 1.5},
    "S09_MFKK_SCALPING":    {"tp_atr": 4.0, "sl_atr": 1.5},
    "S10_OB_FVG_SCALP":     {"tp_atr": 3.5, "sl_atr": 1.5},
    "S16_GOLDEN_SQUEEZE":   {"tp_atr": 3.5, "sl_atr": 2.0},
    "S17_CONVERGENCE_SCALP":{"tp_atr": 4.0, "sl_atr": 1.5},
    "S00_MFKK":             {"tp_atr": 3.5, "sl_atr": 1.5},
    "S18_RANGE_REVERSAL":   {"tp_atr": 2.0, "sl_atr": 1.2},
}

# Estimated trade durations by strategy+TF (minutes) for early-exit detection
TRADE_DURATIONS = {
    ("S00_MFKK",             "M30"): 60,
    ("S05_MFKK_INTRADAY",    "H1"):  180,
    ("S05_MFKK_INTRADAY",    "M30"): 90,
    ("S09_MFKK_SCALPING",    "M5"):  20,
    ("S16_GOLDEN_SQUEEZE",   "H1"):  180,
    ("S16_GOLDEN_SQUEEZE",   "M30"): 90,
    ("S10_OB_FVG_SCALP",     "M30"): 60,
    ("S17_CONVERGENCE_SCALP","H4"):  240,
    ("S17_CONVERGENCE_SCALP","M15"): 30,
    ("S17_CONVERGENCE_SCALP","M5"):  15,
    ("S18_RANGE_REVERSAL",   "M30"): 60,
}

# Circuit breakers
CIRCUIT_BREAKERS = {
    "daily_loss_pct":       0.03,   # halt if today PnL < -3% equity
    "weekly_loss_pct":      0.05,   # halt if weekly DD > 5%
    "consecutive_losses":   5,      # halt after 5 consecutive losses
}

# Composite score minimo per aprire un trade (filtro qualità)
# Backtest: la maggior parte delle perdite avviene con composite < 55 (NORMAL basso).
# Alzare il threshold riduce il numero di trade ma aumenta WR e PF del sistema.
MIN_COMPOSITE_TO_TRADE = 45


def composite_score(strategy_confidence: float,
                    signal_quality: float,
                    market_conditions: float) -> float:
    """
    Weighted composite confidence score [0, 100].
    strategy_confidence: 0-1 from StrategySelector
    signal_quality: 0-1 from indicator confluence (pass AI score / 100 if unavailable)
    market_conditions: 0-1 from ATR stability + session liquidity
    """
    c = (strategy_confidence * 0.50 +
         signal_quality      * 0.30 +
         market_conditions   * 0.20)
    return round(c * 100, 2)


def market_conditions_score(atr: float, atr_avg: float,
                             hour_utc: int, adx: float = None) -> float:
    """Compute a 0-1 score for current market conditions."""
    score = 1.0

    # ATR spike penalty
    if atr and atr_avg and atr_avg > 0:
        ratio = atr / atr_avg
        if ratio > 2.5:
            return 0.0
        elif ratio > 1.8:
            score *= 0.4
        elif ratio > 1.4:
            score *= 0.65
        elif ratio > 1.2:
            score *= 0.85

    # Session liquidity bonus
    if hour_utc is not None:
        if 0 <= hour_utc < 7:
            score *= 0.5
        elif 13 <= hour_utc < 17:
            score *= 1.0   # overlap = best; cap at 1.0 after multiplication
        elif 7 <= hour_utc < 13:
            score *= 0.95
        elif 17 <= hour_utc < 21:
            score *= 0.90
        else:
            score *= 0.70

    # ADX confirmation
    if adx is not None:
        if adx < 15:
            score *= 0.6
        elif adx >= 30:
            score *= 1.0

    return round(min(max(score, 0.0), 1.0), 3)


def assign_risk_tier(comp_score: float,
                     today_pnl: float = 0.0,
                     current_equity: float = None,
                     initial_equity: float = None,
                     weekly_dd_pct: float = 0.0) -> dict:
    """
    Returns a RISK_TIERS entry after applying account-health adjustments.
    """
    adjusted = comp_score

    # Downgrade if account stressed — threshold scales with equity (1.5%, min $30)
    _daily_loss_threshold = -(max(current_equity * 0.015, 30.0)) if (current_equity and current_equity > 0) else -200.0
    if today_pnl < _daily_loss_threshold:
        adjusted -= 10
    if weekly_dd_pct > 0.03:
        adjusted -= 15

    # Upgrade if equity growing + low DD
    if current_equity and initial_equity and initial_equity > 0:
        eq_ratio = current_equity / initial_equity
        if eq_ratio > 1.05 and weekly_dd_pct < 0.02:
            adjusted += 5

    adjusted = max(0.0, min(100.0, adjusted))

    if adjusted >= 85:
        tier_name = "MAX"
    elif adjusted >= 75:
        tier_name = "STRONG"
    elif adjusted >= 60:
        tier_name = "AGGRESSIVE"
    elif adjusted >= 40:
        tier_name = "NORMAL"
    else:
        tier_name = "CONSERVATIVE"

    return {**RISK_TIERS[tier_name], "name": tier_name, "adjusted_score": round(adjusted, 1)}


class RiskGuardian:
    """
    Risk Guardian Agent — manages sizing + position lifecycle.
    """

    def __init__(self, base_lot: float = 0.02, max_lot: float = 0.10,
                 lot_step: float = 0.01, initial_equity: float = 10000.0,
                 compounding_enabled: bool = True):
        self.base_lot = base_lot
        self.max_lot = max_lot
        self.lot_step = lot_step
        self.initial_equity = initial_equity
        self.compounding_enabled = compounding_enabled

        # Position state for BE/TS/early-exit tracking
        # {ticket: {be_done, ts_active, entry_regime, strategy_id, tf, entry_time,
        #           tier_params, tp, sl, direction}}
        self._pos_state: dict = {}

        # Consecutive loss counter for circuit breaker
        self._consecutive_losses: int = 0
        self._last_closed_profits: list = []

        # Last computed order params (exposed to bot_status)
        self._last_params: dict = None

    # ── COMPOSITE SCORE ────────────────────────────────────────────────────────
    def build_composite(self, strategy_confidence: float, ai_score: float,
                        atr: float, atr_avg: float,
                        hour_utc: int, adx: float = None) -> dict:
        """
        Build composite score from available inputs.
        ai_score is used as signal_quality proxy (0-100 → 0-1).
        """
        signal_quality = ai_score / 100.0
        mkt = market_conditions_score(atr, atr_avg, hour_utc, adx)
        comp = composite_score(strategy_confidence, signal_quality, mkt)
        return {
            "strategy_confidence": strategy_confidence,
            "signal_quality": round(signal_quality, 3),
            "market_conditions": mkt,
            "composite_score": comp,
        }

    # ── CIRCUIT BREAKER CHECK ──────────────────────────────────────────────────
    def is_circuit_broken(self, today_pnl: float, current_equity: float,
                          weekly_dd_pct: float) -> tuple:
        """Returns (broken: bool, reason: str)."""
        if current_equity and current_equity > 0:
            daily_pct = today_pnl / current_equity
            if daily_pct < -CIRCUIT_BREAKERS["daily_loss_pct"]:
                return True, f"Daily loss {daily_pct:.1%} exceeds {CIRCUIT_BREAKERS['daily_loss_pct']:.0%} limit"

        if weekly_dd_pct > CIRCUIT_BREAKERS["weekly_loss_pct"]:
            return True, f"Weekly DD {weekly_dd_pct:.1%} exceeds {CIRCUIT_BREAKERS['weekly_loss_pct']:.0%} limit"

        if self._consecutive_losses >= CIRCUIT_BREAKERS["consecutive_losses"]:
            return True, f"{self._consecutive_losses} consecutive losses — halting"

        return False, ""

    # ── PREVIEW (no order, no log) ────────────────────────────────────────────
    def update_preview(self, strategy_confidence: float, ai_score: float,
                       atr: float, atr_avg: float, hour_utc: int,
                       adx: float = None, today_pnl: float = 0.0,
                       current_equity: float = None, weekly_dd_pct: float = 0.0):
        """
        Compute composite+tier without placing an order or logging.
        Updates self._last_params so bot_status always has current RG state.
        """
        try:
            conf = self.build_composite(strategy_confidence, ai_score, atr, atr_avg or atr, hour_utc, adx)
            comp = conf["composite_score"]
            if conf["market_conditions"] == 0.0:
                tier_name, tier_label = "CONSERVATIVE", "🔵 CONSERVATIVE"
                lot = self.base_lot
            else:
                tier = assign_risk_tier(comp, today_pnl, current_equity, self.initial_equity, weekly_dd_pct)
                tier_name, tier_label = tier["name"], tier["label"]
                base_sl_usd = round(atr * tier["sl_multiplier"], 2)
                lot = self._calc_lot(tier, current_equity, base_sl_usd)
            if self._last_params is None:
                self._last_params = {}
            self._last_params.update({
                "composite_score": comp,
                "tier": tier_name,
                "tier_label": tier_label,
                "lot": lot,
            })
        except Exception:
            pass

    # ── ORDER PARAMS ───────────────────────────────────────────────────────────
    def get_order_params(self,
                         strategy_confidence: float,
                         atr: float,
                         strategy_id: str,
                         ai_score: float = 50.0,
                         atr_avg: float = None,
                         adx: float = None,
                         dip: float = None,
                         dim: float = None,
                         hour_utc: int = None,
                         today_pnl: float = 0.0,
                         current_equity: float = None,
                         weekly_dd_pct: float = 0.0,
                         tp_atr_mult: float = None,
                         sl_atr_mult: float = None,
                         direction: str = 'buy') -> dict:
        """
        Compute full order parameters.
        strategy_confidence: 0-1 from StrategySelector.select()['confidence']
        """
        # Build composite confidence
        conf = self.build_composite(
            strategy_confidence, ai_score,
            atr, atr_avg or atr,
            hour_utc or 12, adx
        )
        comp = conf["composite_score"]

        # Market conditions = 0 → hard pause
        if conf["market_conditions"] == 0.0:
            log.warning(f"⛔ RiskGuardian PAUSED [{strategy_id}] — ATR spike/extreme volatility")
            return {"paused": True, "tier": "CONSERVATIVE", "tier_label": "🔵 CONSERVATIVE",
                    "lot": 0.0, "tp_usd": 0.0, "sl_usd": 0.0, "composite_score": comp}

        # Composite < soglia qualità → skip setup low-conviction
        if comp < MIN_COMPOSITE_TO_TRADE:
            log.info(f"⏸ RiskGuardian LOW CONV [{strategy_id}] — comp={comp:.0f} < {MIN_COMPOSITE_TO_TRADE}")
            return {"paused": True, "tier": "CONSERVATIVE", "tier_label": "🔵 CONSERVATIVE",
                    "lot": 0.0, "tp_usd": 0.0, "sl_usd": 0.0, "composite_score": comp,
                    "paused_reason": "low_conviction"}

        # Assign tier
        tier = assign_risk_tier(comp, today_pnl, current_equity,
                                self.initial_equity, weekly_dd_pct)

        # ATR-based TP/SL
        atr_p = STRATEGY_ATR_PARAMS.get(strategy_id, {"tp_atr": 2.0, "sl_atr": 1.0})
        tp_mult = tp_atr_mult if tp_atr_mult else atr_p["tp_atr"]
        sl_mult = sl_atr_mult if sl_atr_mult else atr_p["sl_atr"]

        # ATR spike: allarga SL dinamicamente quando la volatilità è sopra la media.
        # Evita che spike di news o candele ad alto range spazzino SL stretti.
        _atr_ref = atr_avg or atr
        if _atr_ref and _atr_ref > 0:
            _ratio = atr / _atr_ref
            if _ratio > 1.6:
                sl_mult = round(sl_mult * 1.5, 2)
            elif _ratio > 1.3:
                sl_mult = round(sl_mult * 1.3, 2)

        base_tp = round(atr * tp_mult * tier["tp_multiplier"], 2)
        base_sl = round(atr * sl_mult * tier["sl_multiplier"], 2)

        # Lot with compounding
        lot = self._calc_lot(tier, current_equity, base_sl)

        # BE trigger price distance from entry
        be_dist = round(base_tp * tier["be_trigger"], 2)
        # Trailing activation = BE + 5% of TP (activate sooner after BE)
        trailing_activation = round(base_tp * (tier["be_trigger"] + 0.05), 2)
        ts_step_usd = round(atr * 0.3, 2) if atr else round(base_sl * 0.25, 2)

        _atr_note = ""
        if _atr_ref and _atr_ref > 0 and atr / _atr_ref > 1.3:
            _atr_note = f" [ATR×{atr/_atr_ref:.1f} spike→SL×{sl_mult:.2f}]"
        log.info(
            f"🛡️ RiskGuardian [{tier['label']}] strat={strategy_id} "
            f"comp={comp:.0f} (str={strategy_confidence:.2f}/"
            f"sig={conf['signal_quality']:.2f}/mkt={conf['market_conditions']:.2f}) | "
            f"lot={lot} | TP=${base_tp:.2f} SL=${base_sl:.2f}{_atr_note} | "
            f"BE@+${be_dist:.2f} | TS step=${ts_step_usd:.2f}"
        )

        result = {
            "paused": False,
            "lot": lot,
            "tp_usd": base_tp,
            "sl_usd": base_sl,
            "be_trigger": be_dist,
            "trailing_activation": trailing_activation,
            "ts_step": ts_step_usd,
            "early_exit_threshold": tier["early_exit_threshold"],
            "tier": tier["name"],
            "tier_label": tier["label"],
            "composite_score": comp,
            "confidence_breakdown": conf,
            "manip_mult": conf["market_conditions"],  # backward compat alias
        }
        self._last_params = result
        return result

    # ── REGISTER NEW POSITION ──────────────────────────────────────────────────
    def register_position(self, ticket: int, order_params: dict,
                          strategy_id: str, timeframe: str,
                          entry_regime: str, direction: str,
                          partial_targets: list = None):
        """Call after place_order() to track BE/TS state for this ticket."""
        self._pos_state[ticket] = {
            "be_done": False,
            "ts_active": False,
            "partial_done": set(),  # set of target prices already hit
            "partial_targets": partial_targets or [],
            "entry_regime": entry_regime,
            "strategy_id": strategy_id,
            "timeframe": timeframe,
            "entry_time": time.time(),
            "direction": direction,
            "tier_params": order_params,
            "be_trigger": order_params.get("be_trigger", 8.0),
            "ts_step": order_params.get("ts_step", 5.0),
            "trailing_activation": order_params.get("trailing_activation", 10.0),
            "early_exit_threshold": order_params.get("early_exit_threshold", 0.20),
        }

    # ── MANAGE OPEN POSITIONS ──────────────────────────────────────────────────
    def manage_positions(self, mt5_module, symbol: str, magic: int,
                         current_atr: float,
                         current_regime: str = None) -> list:
        """
        Called every ~10s. Manages all open positions:
        1. Break-even placement
        2. Trailing stop activation
        3. Early exit if stalled
        4. Regime-shift override
        Returns list of executed actions.
        """
        mt5 = mt5_module
        actions = []
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            self._cleanup_state(set())
            return actions

        open_tickets = set()
        for pos in positions:
            if pos.magic != magic:
                continue
            open_tickets.add(pos.ticket)

            ticket  = pos.ticket
            entry   = pos.price_open
            curr    = pos.price_current
            sl      = pos.sl
            tp      = pos.tp
            is_buy  = (pos.type == 0)

            # Ensure state entry exists (positions opened before restart)
            if ticket not in self._pos_state:
                atr_strat = STRATEGY_ATR_PARAMS.get("S16_GOLDEN_SQUEEZE", {})
                default_sl = current_atr * atr_strat.get("sl_atr", 1.0) if current_atr else 10.0
                be_dist = default_sl * 0.7
                self._pos_state[ticket] = {
                    "be_done": False,
                    "ts_active": False,
                    "entry_regime": current_regime,
                    "strategy_id": "UNKNOWN",
                    "timeframe": "M30",
                    "entry_time": pos.time,
                    "direction": "buy" if is_buy else "sell",
                    "be_trigger": be_dist,
                    "ts_step": current_atr * 0.3 if current_atr else 2.5,
                    "trailing_activation": be_dist * 1.1,
                    "early_exit_threshold": 0.20,
                }

            ps = self._pos_state[ticket]
            tp_dist = abs(tp - entry) if tp else (current_atr * 2.0 if current_atr else 15.0)
            if tp_dist == 0:
                continue

            dist = (curr - entry) if is_buy else (entry - curr)
            profit_ratio = dist / tp_dist if tp_dist > 0 else 0.0

            # ── 1. BREAK-EVEN ─────────────────────────────────────────────
            be_threshold = ps["be_trigger"] / tp_dist  # both in $, ratio 0-1
            if not ps["be_done"] and profit_ratio >= be_threshold:
                be_sl = round(entry + 0.02, 2) if is_buy else round(entry - 0.02, 2)
                if (is_buy and sl < be_sl) or (not is_buy and (sl == 0 or sl > be_sl)):
                    if self._modify_sl(mt5, pos, be_sl, tp, symbol):
                        ps["be_done"] = True
                        reason = f"Profit {dist:.1f} ≥ BE trigger {ps['be_trigger']:.1f}"
                        log.info(f"🛡️  BE ticket#{ticket}: SL→{be_sl:.2f} — {reason}")
                        actions.append({"type": "be", "ticket": ticket, "sl": be_sl, "reason": reason})

            # ── 2. TRAILING STOP ──────────────────────────────────────────
            trail_dist = ps["ts_step"]
            if ps["be_done"] and dist >= ps.get("trailing_activation", trail_dist):
                if is_buy:
                    ideal_sl = round(curr - trail_dist, 2)
                    if ideal_sl > sl:
                        if self._modify_sl(mt5, pos, ideal_sl, tp, symbol):
                            ps["ts_active"] = True
                            log.info(f"📈 Trail ticket#{ticket}: SL→{ideal_sl:.2f} (+{ideal_sl-entry:.2f})")
                            actions.append({"type": "trail", "ticket": ticket, "sl": ideal_sl})
                else:
                    ideal_sl = round(curr + trail_dist, 2)
                    if sl == 0 or ideal_sl < sl:
                        if self._modify_sl(mt5, pos, ideal_sl, tp, symbol):
                            ps["ts_active"] = True
                            log.info(f"📉 Trail ticket#{ticket}: SL→{ideal_sl:.2f} (-{entry-ideal_sl:.2f})")
                            actions.append({"type": "trail", "ticket": ticket, "sl": ideal_sl})

            # ── 3. PARTIAL CLOSE at key level targets ─────────────────────
            partial_targets = ps.get("partial_targets", [])
            partial_done    = ps.get("partial_done", set())
            if partial_targets and pos.volume >= 0.02:
                for tgt in partial_targets:
                    tgt_price = tgt["price"]
                    if tgt_price in partial_done:
                        continue
                    hit = (is_buy and curr >= tgt_price) or (not is_buy and curr <= tgt_price)
                    if hit:
                        close_vol = self._round_lot(pos.volume * 0.50)
                        if close_vol >= 0.01:
                            ok = self._partial_close(mt5, pos, symbol, close_vol)
                            if ok:
                                partial_done.add(tgt_price)
                                ps["partial_done"] = partial_done
                                reason = (
                                    f"Partial close {close_vol} @ {curr:.2f} — "
                                    f"{tgt['type']} target {tgt_price:.2f}"
                                )
                                log.info(f"🎯  Partial close ticket#{ticket} — {reason}")
                                actions.append({"type": "partial_close", "ticket": ticket,
                                                "volume": close_vol, "reason": reason})
                        break  # only one partial per manage() call

            # ── 4. EARLY EXIT (stalled trade after BE) ────────────────────
            if ps["be_done"] and not ps["ts_active"]:
                elapsed_min = (time.time() - ps["entry_time"]) / 60
                expected_min = TRADE_DURATIONS.get(
                    (ps["strategy_id"], ps["timeframe"]), 90
                )
                if elapsed_min > expected_min * 1.5:
                    if profit_ratio < ps["early_exit_threshold"]:
                        ok = self._close_position(mt5, pos, symbol)
                        if ok:
                            reason = (
                                f"Stalled: {profit_ratio:.0%} profit after "
                                f"{elapsed_min:.0f}min (expected {expected_min}min)"
                            )
                            log.info(f"⏱️  Early exit ticket#{ticket} — {reason}")
                            actions.append({"type": "early_exit", "ticket": ticket, "reason": reason})
                            self._pos_state.pop(ticket, None)
                            continue

            # ── 4. REGIME SHIFT OVERRIDE ──────────────────────────────────
            if current_regime and ps.get("entry_regime"):
                entry_regime_canonical = _canonical_regime(ps["entry_regime"])
                curr_regime_canonical  = _canonical_regime(current_regime)
                if entry_regime_canonical != curr_regime_canonical:
                    # Check if current regime is hostile to the entry strategy
                    entry_strategy_regimes = _get_strategy_optimal_regimes(ps["strategy_id"])
                    if curr_regime_canonical not in entry_strategy_regimes:
                        # Regime is now hostile — close if at BE or better
                        if ps["be_done"] or dist > 0:
                            ok = self._close_position(mt5, pos, symbol)
                            if ok:
                                reason = (
                                    f"Regime shift: {ps['entry_regime']} → {current_regime} "
                                    f"(hostile to {ps['strategy_id']})"
                                )
                                log.info(f"🔄 Regime exit ticket#{ticket} — {reason}")
                                actions.append({"type": "regime_exit", "ticket": ticket, "reason": reason})
                                self._pos_state.pop(ticket, None)
                                continue

        self._cleanup_state(open_tickets)
        return actions

    # ── RECORD TRADE RESULT (for circuit breaker) ──────────────────────────────
    def record_trade_result(self, profit: float):
        """Call when a trade closes to update consecutive loss counter."""
        self._last_closed_profits.append(profit)
        if profit <= 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

    # ── HELPERS ────────────────────────────────────────────────────────────────
    def _calc_lot(self, tier: dict, current_equity: float = None,
                  base_sl_usd: float = None) -> float:
        """Lot with optional compounding, capped at max_lot and 2% risk."""
        eq_ratio = 1.0
        if self.compounding_enabled and current_equity and self.initial_equity > 0:
            raw_ratio = current_equity / self.initial_equity
            eq_ratio = min(raw_ratio ** 0.5, 3.0)

        raw_lot = self.base_lot * tier["lot_multiplier"] * eq_ratio

        # 2% risk cap: max_lot_by_risk = equity * 0.02 / (sl_pips × pip_value)
        if current_equity and base_sl_usd and base_sl_usd > 0:
            # Approximate: sl_usd = sl_price × lot × contract_size
            # For GOLD on XM: 1 lot = 100oz, pip=$0.01 → $1/pip/lot
            # So lot = equity*0.02 / sl_in_usd_per_lot
            # sl_usd here is already in dollar per 0.01lot (strategy engine units)
            max_by_risk = (current_equity * 0.02) / (base_sl_usd / self.base_lot)
            raw_lot = min(raw_lot, max_by_risk)

        return self._round_lot(raw_lot)

    def _round_lot(self, lot: float) -> float:
        lot = max(0.01, min(self.max_lot, lot))
        steps = round(lot / self.lot_step)
        return round(steps * self.lot_step, 2)

    def _modify_sl(self, mt5, pos, new_sl: float, tp: float, symbol: str) -> bool:
        req = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "symbol":   symbol,
            "position": pos.ticket,
            "sl":       new_sl,
            "tp":       tp,
        }
        result = mt5.order_send(req)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            return True
        log.warning(f"⚠️  Modify SL failed ticket#{pos.ticket}: {result.comment if result else 'err'}")
        return False

    def _partial_close(self, mt5, pos, symbol: str, volume: float) -> bool:
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return False
        close_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
        price = tick.bid if pos.type == 0 else tick.ask
        req = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       volume,
            "type":         close_type,
            "position":     pos.ticket,
            "price":        price,
            "deviation":    20,
            "magic":        pos.magic,
            "comment":      "TF-AI partial",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(req)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            return True
        log.warning(f"⚠️  Partial close failed ticket#{pos.ticket}: {result.comment if result else 'err'}")
        return False

    def _close_position(self, mt5, pos, symbol: str) -> bool:
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return False
        close_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
        price = tick.bid if pos.type == 0 else tick.ask
        req = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       pos.volume,
            "type":         close_type,
            "position":     pos.ticket,
            "price":        price,
            "deviation":    20,
            "magic":        pos.magic,
            "comment":      "TF-AI guardian",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(req)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            return True
        log.warning(f"⚠️  Close position failed ticket#{pos.ticket}: {result.comment if result else 'err'}")
        return False

    def _cleanup_state(self, open_tickets: set):
        for t in list(self._pos_state.keys()):
            if t not in open_tickets:
                del self._pos_state[t]

    # ── BACKWARD COMPAT (drop-in for risk_manager.get_order_params) ───────────
    def get_order_params_legacy(self, ai_score: float, atr: float,
                                strategy: str, **kwargs) -> dict:
        """Legacy wrapper: uses ai_score/100 as strategy_confidence."""
        return self.get_order_params(
            strategy_confidence=ai_score / 100.0,
            atr=atr,
            strategy_id=strategy,
            ai_score=ai_score,
            **kwargs
        )


# ── HELPERS (module-level) ─────────────────────────────────────────────────────
def _canonical_regime(r: str) -> str:
    mapping = {
        "TREND_UP": "TREND", "TREND_DOWN": "TREND",
        "WEAK_UP": "WEAK",   "WEAK_DOWN": "WEAK",
        "WEAK": "WEAK",      "RANGING": "RANGE", "RANGE": "RANGE",
        "VOLATILE": "VOLATILE", "EXTREME": "VOLATILE",
    }
    return mapping.get(r, "UNKNOWN")


def _get_strategy_optimal_regimes(strategy_id: str) -> list:
    # Canonical regimes that this strategy tolerates
    mapping = {
        "S05_MFKK_INTRADAY":    ["TREND"],
        "S09_MFKK_SCALPING":    ["VOLATILE", "WEAK"],
        "S10_OB_FVG_SCALP":     ["RANGE", "WEAK"],
        "S16_GOLDEN_SQUEEZE":   ["TREND", "WEAK"],
        "S17_CONVERGENCE_SCALP":["VOLATILE", "TREND"],
        "S00_MFKK":             ["TREND", "WEAK", "RANGE", "VOLATILE"],
        "S18_RANGE_REVERSAL":   ["RANGE", "WEAK"],
    }
    return mapping.get(strategy_id, ["TREND", "WEAK", "RANGE", "VOLATILE"])


# ── SINGLETON ──────────────────────────────────────────────────────────────────
_rg_instance = None

def get_risk_guardian(base_lot: float = 0.02, max_lot: float = 0.10,
                      initial_equity: float = 10000.0) -> RiskGuardian:
    global _rg_instance
    if _rg_instance is None:
        _rg_instance = RiskGuardian(base_lot=base_lot, max_lot=max_lot,
                                    initial_equity=initial_equity)
    return _rg_instance
