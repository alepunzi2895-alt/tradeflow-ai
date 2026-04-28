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
    # Exhaustion check
    is_exh_sell = s_adx_s >= 75 and b_diff > 1.0 # MACD very bullish but ADX/DI favor sell
    is_exh_buy  = b_adx_s >= 75 and b_diff < -1.0 # MACD very bearish but ADX/DI favor buy

    # High-WR Sell (exact hard rules)
    is_london_ny = hour is not None and (7 <= hour < 17)
    is_high_wr_sell = (not b_cross) and a >= 35 and dm > dp and (dm-dp) >= 20 and b_diff >= 1.0 and c >= 25 and is_london_ny

    # DI spread gate: require at least minimal directional conviction
    if abs(dp - dm) < 5: return None

    # Final Decision
    if is_high_wr_sell: return 'sell'

    # Thresholds: Buy >= 90 (or 82 for special), Sell >= 72 (raised from 68)
    buy_thr = 82 if (is_exh_buy or b_cross) else 90
    sell_thr = 72

    if b_score >= buy_thr: return 'buy'
    if s_score >= sell_thr: return 'sell'

    return None


def signal_mfkk_intraday(ind, i, h1_trend=None, hour=None, ai_score=0):
    """S05_MFKK_INTRADAY V3 — OBV T-Channel + RSI + MACD + Mom + ADX + EMA200.
    Opt: RSI 55/45, ADX>=15 gate, StochRSI K>D confluence.
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

    # ADX gate — skip flat/choppy markets (15 instead of 20 to reduce over-filtering)
    if a < 15: return None

    # StochRSI K>D: momentum turning in entry direction
    srsi_bull = (sk is None or sd is None) or (sk > sd)
    srsi_bear = (sk is None or sd is None) or (sk < sd)

    # Tightened RSI thresholds (54/46 vs original 52/48) to reduce weak entries
    is_buy  = oc[i] == 1  and r > 54 and mo > 0 and mc > 0 and close > e200 and srsi_bull
    is_sell = oc[i] == -1 and r < 46 and mo < 0 and mc < 0 and close < e200 and srsi_bear
    if is_buy:  return 'buy'
    if is_sell: return 'sell'
    return None


def signal_golden_squeeze(ind, i, h1_trend=None, hour=None, h4_trend=None):
    """S16: ELITE CONFLUENCE V4 — OBV Momentum + Trend Alignment + H4 context filter.
    V3 (2026-04-23): ADX>=25, DI agreement, 3-bar OBV slope, candle>=0.35×ATR.
    V4 (2026-04-28): SELL only when H4 is BULLISH (countertrend into uptrend, WR 50%).
      When H4 bearish (trend-following sell), WR drops to 31% — exhausted move, late entry.
      Bot: h4_trend=-1 required for SELL. Backtester proxy: EMA200 rising over 4 bars.
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

    # OBV 3-bar slope: sustained volume momentum (was 1-bar → too noisy)
    obv_rising_3 = i >= 3 and obv_arr[i] > obv_arr[i - 1] > obv_arr[i - 2]
    obv_falling_3 = i >= 3 and obv_arr[i] < obv_arr[i - 1] < obv_arr[i - 2]

    if st == -1:  # BULLISH
        if dip_v <= dim_v: return None  # DI+ must dominate for BUY
        if c > e233 and obv_val > obv_ema and obv_rising_3 and c > cp and big_enough:
            return 'buy'
    elif st == 1:  # BEARISH
        if dim_v <= dip_v: return None  # DI- must dominate for SELL
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
        if c < e233 and obv_val < obv_ema and obv_falling_3 and c < cp and big_enough:
            return 'sell'
    return None


def signal_mfkk_scalping(ind, i, h1_trend=None, hour=None):
    """S09_MFKK_SCALPING V2 — EMA Fibonacci Stack (13,34,89,233) + FVG retest.
    Note: FVG retests are reliable even in flat markets (ADX < 14) — no ADX gate.
    """
    if i < 233: return None
    e13 = ind['e13'][i]; e34 = ind['e34'][i]; e89 = ind['e89'][i]; e233 = ind['e233'][i]
    fb = ind.get('fvg_bull'); fs = ind.get('fvg_bear')
    c = ind['C'][i]
    if None in (e13, e34, e89, e233) or fb is None: return None
    if e13 > e34 > e89 > e233 and c > e233 and fb[i]: return 'buy'
    if e13 < e34 < e89 < e233 and c < e233 and fs[i]: return 'sell'
    return None


def signal_ob_fvg_scalp(ind, i, h1_trend=None, hour=None):
    """S10_OB_FVG_SCALP V2 — ICT Order Block + FVG + EMA 233 Trend Filter.
    Opt: skip ATR spike (>2.5×avg) to avoid news-driven false OB retests.
    """
    if i < 233: return None
    ob_b = ind.get('ob_bull'); ob_s = ind.get('ob_bear')
    fb = ind.get('fvg_bull'); fs = ind.get('fvg_bear')
    e233 = ind['e233'][i]; c = ind['C'][i]
    if ob_b is None or fb is None or e233 is None: return None

    # Skip during ATR spikes (news events distort OB/FVG validity)
    atr_arr = ind.get('atr')
    atr_ref  = _get(ind, 'atr_avg', 'atr30')
    atr = atr_arr[i] if atr_arr else 0
    atr_avg = atr_ref[i] if atr_ref else 0
    if atr_avg and atr > 2.5 * atr_avg: return None

    if ob_b[i] and fb[i] and c > e233: return 'buy'
    if ob_s[i] and fs[i] and c < e233: return 'sell'
    return None


def signal_convergence_scalp(ind, i, h1_trend=None, hour=None):
    """S17_CONVERGENCE_SCALP V2 — EMA 34/89 crossover + StochRSI + BB %B + EMA50.
    Optimal TF: H4 (PF 1.710) >> M30. Opt: ADX>=18 gate + BB%B 0.55/0.45 tighter.
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

    # ADX >= 18: EMA crossovers need at least modest directional bias
    if a is not None and a < 18: return None

    bb_range = bbu - bbl
    bb_pct = (c - bbl) / bb_range if bb_range > 0 else 0.5
    e34_p = ind['e34'][i - 1]; e89_p = ind['e89'][i - 1]
    sk_p = ind['srsi_k'][i - 1]; sd_p = ind['srsi_d'][i - 1]
    if None in (e34_p, e89_p, sk_p, sd_p): return None

    bull_prev = e34_p > e89_p and sk_p > sd_p
    bear_prev = e34_p < e89_p and sk_p < sd_p
    # BB%B tightened 0.55/0.45: price must be clearly above/below midline
    bull = e34 > e89 and sk > sd and bb_pct > 0.55 and c > e50 and not bull_prev
    bear = e34 < e89 and sk < sd and bb_pct < 0.45 and c < e50 and not bear_prev

    if bull: return 'buy'
    if bear: return 'sell'
    return None
