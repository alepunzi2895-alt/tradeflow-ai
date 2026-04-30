"""
TradeFlow AI — Unified Signal Functions
Single source of truth imported by mt5-bot.py and strategy-engine-v2.py.

Key naming conventions (both dicts supported via fallback):
  MACD line       : 'ml'  (mt5-bot) / 'macd'         (strategy-engine-v2)
  OBV MACD cross  : 'obv_oc' (mt5-bot) / 'obv_macd_oc'  (strategy-engine-v2)
  BB lower band   : 'bb_dn' (mt5-bot) / 'bb_lo'         (strategy-engine-v2)
  ATR rolling avg : 'atr_avg' (mt5-bot) / 'atr30'        (strategy-engine-v2)

Optimization 2026-04-19:
  S16: ADX>=20 gate + OBV 1-bar slope + candle>=0.20×ATR + session 7-18 UTC
  S05: StochRSI K>D confluence (buy) / K<D (sell) added
  S09: no change — FVG retests reliable in flat markets, filters hurt WR
  S00: sell threshold raised 68→72, DI spread>=5 gate
  S10: skip ATR spike (>2.5×avg)  [unchanged]
  S17: ADX>=18 gate + BB%B tightened 0.55/0.45

Optimization 2026-04-30 (WR improvement pass):
  S05: ADX 15→18, RSI 54/46→57/43, RSI slope confirmation (r > r_prev)
  S09: ADX≥15 gate + RSI>50/<50 + OBV vs OBV_EMA volume confirmation
  S16: OBV slope 3→4 barre consecutive, DI spread esplicito ≥8
  S17: ADX 18→22, BB%B 0.55/0.45→0.62/0.38, candle direction filter
  S00: sell DI spread 20→25, sell_thr 72→76
"""


def _get(ind, *keys):
    """Return first non-None array found among the given key names."""
    for k in keys:
        v = ind.get(k)
        if v is not None:
            return v
    return None


def signal_mfkk_score(ind, i, h1_trend=None, hour=None, tf=None):
    """
    S00_MFKK — Highly specialized multi-tier scoring (port of mfkk.js).
    Weights: CCI 10%, MACD 10%, ADX 80% (XAU optimized).
    """
    if i < 100: return None
    # H4: block only true dead zone (0-3 UTC, 1 bar/day)
    # M30/H1: block Asia chop 0-6 UTC + NY close chop 22-23 UTC
    if hour is not None:
        if tf == 'H4':
            if hour < 4: return None
        elif not (7 <= hour < 22): return None

    # ── RAW VALUES ──────────────────────────────────────────────────────────
    # Note: 'cci' here refers to the stk_d (smoothed stochastic of CCI) passed by compute_all
    c = ind['cci'][i]
    if c is None: c = 50.0

    ml_arr = _get(ind, 'ml', 'macd')
    m = ml_arr[i] if ml_arr else 0
    m_sig = ind.get('macd_sig', [0]*len(ml_arr))[i] if ml_arr else 0
    m_hist = ind.get('macd_hist', [0]*len(ml_arr))[i] if ml_arr else 0
    m_hist_p = ind.get('macd_hist', [0]*len(ml_arr))[i-1] if (ml_arr and i>0) else 0

    a  = ind['adx'][i]
    dp = ind['dip'][i]
    dm = ind['dim'][i]
    if None in (a, dp, dm): return None

    # ── DIRECTION DETECTION (for scoring bias) ──────────────────────────────
    # We calculate both and return 'buy' or 'sell' if one crosses threshold
    def get_dir_score(is_buy):
        # 1. CCI SCORE (10%) — exact tiered logic from mfkk.js
        cci_s = 50
        if is_buy:
            macd_rising = m_hist > m_hist_p
            is_cci_reversal = c < 35 and (macd_rising or m > m_sig)
            if is_cci_reversal:    cci_s = 85 + (35 - c) * 0.5
            elif c >= 75:          cci_s = 70
            elif c >= 65:          cci_s = 55
            elif c >= 50:          cci_s = 45
            elif c >= 35:          cci_s = 35
            else:                  cci_s = 20
        else:
            macd_falling = m_hist < m_hist_p
            is_cci_reversal = c > 65 and (macd_falling or m < m_sig)
            if is_cci_reversal:    cci_s = 85 + (c - 65) * 0.5
            elif c <= 35:          cci_s = 15
            elif c <= 50:          cci_s = 40
            elif c <= 65:          cci_s = 50
            else:                  cci_s = 20

        # 2. MACD SCORE (10%)
        macd_s = 50
        diff = m - m_sig
        str_m = min(abs(diff)/3, 1)
        hist_bonus = 10 if ((is_buy and m_hist > 0) or (not is_buy and m_hist < 0)) else 0

        m_p = ml_arr[i-1] if i>0 else 0
        ms_p = ind.get('macd_sig', [0]*len(ml_arr))[i-1] if i>0 else 0

        cross_buy = m_p <= ms_p and m > m_sig
        cross_sell = m_p >= ms_p and m < m_sig

        if is_buy:
            if cross_buy:          macd_s = 100
            elif diff > 0.5:       macd_s = 75 + str_m * 20 + hist_bonus
            elif diff > 0:         macd_s = 70 + hist_bonus
            elif diff > -0.2:      macd_s = 60
            elif diff > -1:        macd_s = 40
            elif diff > -3:        macd_s = 45 # exhaustion hint
            else:                  macd_s = 20
        else:
            if cross_sell:         macd_s = 100
            elif cross_buy:        macd_s = 5
            elif diff < -0.5:      macd_s = 75 + str_m * 20 + hist_bonus
            elif diff < 0:         macd_s = 70 + hist_bonus
            elif diff < 0.5:       macd_s = 45
            elif diff < 3:         macd_s = 50 # inversion setup
            else:                  macd_s = 20

        # 3. ADX SCORE (80%)
        adx_s = 50
        di_diff = dp - dm
        di_spread = abs(di_diff)
        spread_bonus = min(di_spread / 20, 1) * 15
        adx_str = 1.0 if a>=35 else 0.85 if a>=27 else 0.65 if a>=20 else 0.4 if a>=14 else 0.2 if a>=10 else 0.05

        if is_buy:
            if di_diff > 0 and a >= 25:   adx_s = 60 + adx_str * 25 + spread_bonus
            elif di_diff > 0 and a >= 10: adx_s = 50
            elif di_diff > 0:             adx_s = 30
            elif di_diff < 0 and a >= 35: adx_s = 60 + adx_str * 25 + spread_bonus # reversal
            else:                         adx_s = 5
        else:
            if di_diff < 0 and a >= 25:   adx_s = 60 + adx_str * 25 + spread_bonus
            elif di_diff < 0 and a >= 10: adx_s = 50
            elif di_diff < 0:             adx_s = 30
            elif di_diff > 0 and a >= 35: adx_s = 60 + adx_str * 25 + spread_bonus # reversal
            else:                         adx_s = 5

        # Weighted Total
        total = (cci_s * 0.10) + (macd_s * 0.10) + (adx_s * 0.80)
        return total, adx_s, diff, cross_buy, cross_sell

    # Execute scoring
    b_score, b_adx_s, b_diff, b_cross, b_cross_s = get_dir_score(True)
    s_score, s_adx_s, s_diff, s_cross_b, s_cross = get_dir_score(False)

    # ── SPECIAL PATTERNS ────────────────────────────────────────────────────
    # Exhaustion check (buy only — sell exhaustion not reliable, see V2 analysis)
    is_exh_buy = b_adx_s >= 75 and b_diff < -1.0  # MACD very bearish but ADX/DI favor buy

    # DI spread gate: require at least minimal directional conviction
    if abs(dp - dm) < 5: return None

    # ── BUY: ST alignment + strong DI conviction filter ─────────────────────
    # Analysis (2026-04-28): BUY ST-aligned + DI≥20 → WR 28.3%, PF 1.38
    # Without ST filter all buys have WR 24.7%, PF 1.15 (fine but weaker)
    st_arr = ind.get('st')
    st_now = st_arr[i] if st_arr else 0
    buy_thr = 82 if (is_exh_buy or b_cross) else 90
    # Tighten BUY: require DI≥20 aligned OR Supertrend bullish when DI<20
    buy_di_spread = dp - dm
    buy_di_ok = buy_di_spread >= 20
    buy_st_ok = (st_now == -1)  # H1 Supertrend bullish
    if not (buy_di_ok or buy_st_ok): buy_thr = 999  # block low-conviction buys

    # ── SELL: London/NY session + strong DI conviction only ─────────────────
    # Analysis (2026-04-28): SELL with DI≥20 + sess 7-17h → WR 24.1%, PF 1.11 (M30/H1)
    # H4 SELL is unreliable (WR 17.5%) — block entirely on H4
    sell_thr = 999  # block by default
    is_london_ny = hour is not None and (7 <= hour < 17)
    sell_di_spread = dm - dp
    if tf != 'H4' and is_london_ny and sell_di_spread >= 25:
        sell_thr = 76

    if b_score >= buy_thr: return 'buy'
    if s_score >= sell_thr: return 'sell'

    return None


def signal_mfkk_intraday(ind, i, h1_trend=None, hour=None, ai_score=0):
    """S05_MFKK_INTRADAY V4 — OBV T-Channel + RSI + MACD + Mom + ADX + EMA200 + ST alignment.
    V3: RSI 55/45, ADX>=15 gate, StochRSI K>D confluence.
    V4 (2026-04-28): Supertrend alignment filter — buy only when ST bullish, sell only when ST bearish.
      Removes counter-ST entries that drove H1 losses. h1_trend=-1=bullish, 1=bearish.
    """
    if i < 2: return None
    oc = _get(ind, 'obv_oc', 'obv_macd_oc')
    if not oc or i >= len(oc): return None
    r = ind['rsi'][i]; mo = ind['mom'][i]; a = ind['adx'][i]
    ml = _get(ind, 'ml', 'macd')
    mc = ml[i] if ml else None
    e200 = ind['e200'][i]; close = ind['C'][i]
    sk = ind.get('srsi_k', [None] * (i + 1))[i]
    sd = ind.get('srsi_d', [None] * (i + 1))[i]
    if None in (r, mo, a, mc, e200): return None

    # ADX gate — skip flat/choppy markets
    if a < 18: return None

    # Session filter: London+NY only (cleaner OBV signals, lower DD on H1 deployment)
    if hour is not None and not (7 <= hour < 17): return None

    # ATR spike filter: skip extreme volatility bars (news events, overextended entries)
    atr_arr = ind.get('atr')
    atr_ref = _get(ind, 'atr_avg', 'atr30')
    atr_v = atr_arr[i] if atr_arr else None
    atr_avg_v = atr_ref[i] if atr_ref else None
    if atr_v and atr_avg_v and atr_v > 1.8 * atr_avg_v: return None

    # Supertrend alignment: only trade in ST direction (V4)
    if h1_trend is not None and h1_trend != 0:
        if oc[i] == 1 and h1_trend != -1: return None   # BUY only when ST bullish
        if oc[i] == -1 and h1_trend != 1: return None   # SELL only when ST bearish

    # StochRSI K>D: momentum turning in entry direction
    srsi_bull = (sk is None or sd is None) or (sk > sd)
    srsi_bear = (sk is None or sd is None) or (sk < sd)

    rp = ind['rsi'][i - 1] if i > 0 else r
    is_buy  = oc[i] == 1  and r > 57 and r > rp and mo > 0 and mc > 0 and close > e200 and srsi_bull
    is_sell = oc[i] == -1 and r < 43 and r < rp and mo < 0 and mc < 0 and close < e200 and srsi_bear
    if is_buy:  return 'buy'
    if is_sell: return 'sell'
    return None


def signal_golden_squeeze(ind, i, h1_trend=None, hour=None, h4_trend=None):
    """S16: ELITE CONFLUENCE V5 — OBV Momentum + Trend Alignment + H4 context filter.
    V3 (2026-04-23): ADX>=25, DI agreement, 3-bar OBV slope, candle>=0.35×ATR.
    V4 (2026-04-28): SELL only when H4 is BULLISH (countertrend into uptrend, WR 50%).
    V5 (2026-04-30): OBV slope 3→4 barre, DI spread esplicito ≥8 (era solo DI+>DI-).
    """
    if i < 233: return None
    # Session filter: London + NY only (XAU/USD cleaner directional moves)
    if hour is not None and not (7 <= hour < 18): return None

    # h1_trend: explicit H1 Supertrend value from bot; None → use ind['st'] proxy (backtester)
    if h1_trend is not None:
        st = h1_trend
    else:
        st_arr = ind.get('st')
        st = st_arr[i] if st_arr else 0
    if st == 0: return None

    # ADX >= 25 gate (was 20): only trade in strong trends
    a = ind['adx'][i]
    if a is None or a < 25: return None

    # DI directional agreement: trade direction must match DI dominance
    dip_v = ind['dip'][i]; dim_v = ind['dim'][i]
    if None in (dip_v, dim_v): return None

    obv_arr = ind.get('obv'); obv_ema_arr = ind.get('obv_ema')
    if obv_arr is None or obv_ema_arr is None: return None
    obv_val = obv_arr[i]; obv_ema = obv_ema_arr[i]
    c = ind['C'][i]; cp = ind['C'][i - 1]; e233 = ind['e233'][i]
    if None in (obv_val, obv_ema, e233): return None

    # Candle size filter: require meaningful bar (0.35×ATR, was 0.20 → too many Doji entries)
    atr_arr = ind.get('atr')
    atr_val = atr_arr[i] if atr_arr else None
    candle = abs(c - cp)
    big_enough = (atr_val is None) or (candle >= 0.35 * atr_val)

    # OBV 4-bar slope: sustained volume momentum (was 3-bar → still some noise)
    obv_rising_4  = i >= 4 and obv_arr[i] > obv_arr[i-1] > obv_arr[i-2] > obv_arr[i-3]
    obv_falling_4 = i >= 4 and obv_arr[i] < obv_arr[i-1] < obv_arr[i-2] < obv_arr[i-3]

    if st == -1:  # BULLISH
        if dip_v - dim_v < 8: return None  # DI+ must dominate for BUY with spread ≥8
        if c > e233 and obv_val > obv_ema and obv_rising_4 and c > cp and big_enough:
            return 'buy'
    elif st == 1:  # BEARISH
        if dim_v - dip_v < 8: return None  # DI- must dominate for SELL with spread ≥8
        # H4 trend filter: on XAU/USD, SELL works best as a countertrend within a medium-term uptrend.
        # When H4 is bearish (medium-term downtrend), SELL WR drops to ~31% (late-trend chase, exhausted move).
        # When H4 is bullish (medium-term uptrend), SELL WR rises to ~50% (short pullback, clean reversal).
        if h4_trend is not None:
            if h4_trend != -1: return None  # bot: actual H4 ST must be BULLISH (countertrend sell)
        else:
            # backtester proxy: EMA200 must be rising over 4 bars (medium-term uptrend = countertrend setup)
            e200_arr = ind.get('e200')
            if e200_arr is not None and i >= 4:
                e200_now = e200_arr[i]; e200_prev = e200_arr[i - 4]
                if e200_now is not None and e200_prev is not None and e200_now <= e200_prev:
                    return None
        if c < e233 and obv_val < obv_ema and obv_falling_4 and c < cp and big_enough:
            return 'sell'
    return None


def signal_mfkk_scalping(ind, i, h1_trend=None, hour=None):
    """S09_MFKK_SCALPING V4 — EMA Fibonacci Stack (13,34,89,233) + FVG retest + session + ST gate.
    V2: no ADX gate — FVG retests reliable in flat markets.
    V3 (2026-04-28): London/NY session filter (7-17h) + ST alignment when available.
    V4 (2026-04-30): ADX≥15 gate + RSI>50/<50 + OBV vs OBV_EMA volume confirmation.
      Removes low-conviction FVG retests without institutional participation.
    """
    if i < 233: return None

    # Session filter: FVG retests work best in liquid sessions (London open + NY, allow some overlap)
    if hour is not None and not (6 <= hour < 19): return None

    e13 = ind['e13'][i]; e34 = ind['e34'][i]; e89 = ind['e89'][i]; e233 = ind['e233'][i]
    fb = ind.get('fvg_bull'); fs = ind.get('fvg_bear')
    c = ind['C'][i]
    if None in (e13, e34, e89, e233) or fb is None: return None

    # ADX gate: avoid dead-flat markets where FVG retests fail
    a_arr = ind.get('adx')
    a = a_arr[i] if a_arr else None
    if a is not None and a < 15: return None

    # RSI momentum: price must be on the right side of neutral
    r_arr = ind.get('rsi')
    r = r_arr[i] if r_arr else None

    # OBV volume: institutional participation aligned with direction
    obv_arr_s = ind.get('obv'); obv_ema_arr_s = ind.get('obv_ema')
    obv_s = obv_arr_s[i] if obv_arr_s else None
    oe_s  = obv_ema_arr_s[i] if obv_ema_arr_s else None

    # Confirmation flags (pass-through when data unavailable)
    rsi_bull = r is None or r > 50
    rsi_bear = r is None or r < 50
    obv_bull = obv_s is None or oe_s is None or obv_s > oe_s
    obv_bear = obv_s is None or oe_s is None or obv_s < oe_s

    # ST alignment: block counter-trend FVG retests
    if h1_trend is not None and h1_trend != 0:
        if e13 > e34 > e89 > e233 and h1_trend != -1: return None  # BUY: need ST bullish
        if e13 < e34 < e89 < e233 and h1_trend != 1: return None   # SELL: need ST bearish

    if e13 > e34 > e89 > e233 and c > e233 and fb[i] and rsi_bull and obv_bull: return 'buy'
    if e13 < e34 < e89 < e233 and c < e233 and fs[i] and rsi_bear and obv_bear: return 'sell'
    return None


def signal_ob_fvg_scalp(ind, i, h1_trend=None, hour=None):
    """S10_OB_FVG_SCALP V3 — ICT Order Block + FVG + EMA 233 + ST alignment + ADX gate.
    V2: skip ATR spike (>2.5×avg).
    V3 (2026-04-28): Supertrend alignment + ADX>=18 gate.
      OB+FVG setups in ST-aligned direction have higher follow-through (WR improvement).
      ADX>=18 avoids trading dead-flat structure where OBs get immediately re-tested.
    """
    if i < 233: return None
    ob_b = ind.get('ob_bull'); ob_s = ind.get('ob_bear')
    fb = ind.get('fvg_bull'); fs = ind.get('fvg_bear')
    e233 = ind['e233'][i]; c = ind['C'][i]
    a = ind.get('adx', [None]*(i+1))[i]
    if ob_b is None or fb is None or e233 is None: return None

    # ADX gate: require at least minimal directional bias
    if a is not None and a < 18: return None

    # Skip during ATR spikes (news events distort OB/FVG validity)
    atr_arr = ind.get('atr')
    atr_ref  = _get(ind, 'atr_avg', 'atr30')
    atr = atr_arr[i] if atr_arr else 0
    atr_avg = atr_ref[i] if atr_ref else 0
    if atr_avg and atr > 2.5 * atr_avg: return None

    # Supertrend alignment
    if h1_trend is not None and h1_trend != 0:
        if ob_b[i] and fb[i] and h1_trend != -1: return None  # BUY: need ST bullish
        if ob_s[i] and fs[i] and h1_trend != 1: return None   # SELL: need ST bearish

    if ob_b[i] and fb[i] and c > e233: return 'buy'
    if ob_s[i] and fs[i] and c < e233: return 'sell'
    return None


def signal_convergence_scalp(ind, i, h1_trend=None, hour=None):
    """S17_CONVERGENCE_SCALP V3 — EMA 34/89 crossover + StochRSI + BB %B + EMA50.
    V2: ADX>=18 gate + BB%B 0.55/0.45 tighter.
    V3 (2026-04-30): ADX 18→22, BB%B 0.55/0.45→0.58/0.42 (candle filter rimosso: su H4 taglia vincitori).
    """
    if i < 89: return None
    e34 = ind['e34'][i]; e89 = ind['e89'][i]
    sk = ind['srsi_k'][i]; sd = ind['srsi_d'][i]
    bbu = ind['bb_up'][i]
    bbl_arr = _get(ind, 'bb_dn', 'bb_lo')
    bbl = bbl_arr[i] if bbl_arr else None
    c = ind['C'][i]; e50 = ind['e50'][i]; atr = ind['atr'][i]
    a = ind['adx'][i]
    atr_ref = _get(ind, 'atr_avg', 'atr30')
    atr_avg = atr_ref[i] if atr_ref else None
    if None in (e34, e89, sk, sd, bbu, bbl, c, e50, atr): return None
    if atr_avg and atr > 2.2 * atr_avg: return None

    # ADX >= 22: EMA crossovers on H4 need clearer directional bias
    if a is not None and a < 22: return None

    bb_range = bbu - bbl
    bb_pct = (c - bbl) / bb_range if bb_range > 0 else 0.5
    e34_p = ind['e34'][i - 1]; e89_p = ind['e89'][i - 1]
    sk_p = ind['srsi_k'][i - 1]; sd_p = ind['srsi_d'][i - 1]
    if None in (e34_p, e89_p, sk_p, sd_p): return None

    bull_prev = e34_p > e89_p and sk_p > sd_p
    bear_prev = e34_p < e89_p and sk_p < sd_p
    # BB%B tightened 0.55/0.45: price must be clearly above/below midline
    bull = e34 > e89 and sk > sd and bb_pct > 0.58 and c > e50 and not bull_prev
    bear = e34 < e89 and sk < sd and bb_pct < 0.42 and c < e50 and not bear_prev

    if bull: return 'buy'
    if bear: return 'sell'
    return None
