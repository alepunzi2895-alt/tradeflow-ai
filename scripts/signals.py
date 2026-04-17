"""
TradeFlow AI — Unified Signal Functions
Single source of truth imported by mt5-bot.py and strategy-engine-v2.py.

Key naming conventions (both dicts supported via fallback):
  MACD line       : 'ml'  (mt5-bot) / 'macd'         (strategy-engine-v2)
  OBV MACD cross  : 'obv_oc' (mt5-bot) / 'obv_macd_oc'  (strategy-engine-v2)
  BB lower band   : 'bb_dn' (mt5-bot) / 'bb_lo'         (strategy-engine-v2)
  ATR rolling avg : 'atr_avg' (mt5-bot) / 'atr30'        (strategy-engine-v2)
"""


def _get(ind, *keys):
    """Return first non-None array found among the given key names."""
    for k in keys:
        v = ind.get(k)
        if v is not None:
            return v
    return None


def signal_mfkk_score(ind, i, h1_trend=None, hour=None):
    """S00_MFKK — ADX 80% + MACD 10% + CCI 10%. BUY/SELL threshold 65."""
    if i < 50: return None
    a = ind['adx'][i]; dp = ind['dip'][i]; dm = ind['dim'][i]
    ml = _get(ind, 'ml', 'macd')
    m = ml[i] if ml else None
    cci_arr = ind.get('cci')
    c = cci_arr[i] if (cci_arr and cci_arr[i] is not None) else 0
    if None in (a, dp, dm, m): return None

    bull = bear = 0.0
    adx_c = min(a / 40 * 100, 100)
    if dm > dp: bear += adx_c * 0.80
    else:       bull += adx_c * 0.80
    ms = min(abs(m) / 0.5 * 100, 100)
    if m >= 0: bull += ms * 0.10
    else:      bear += ms * 0.10
    cs = min(abs(c) / 100 * 100, 100)
    if c >= 0: bull += cs * 0.10
    else:      bear += cs * 0.10

    if bull >= 65: return 'buy'
    if bear >= 65: return 'sell'
    return None


def signal_mfkk_intraday(ind, i, h1_trend=None, hour=None, ai_score=0):
    """S05_MFKK_INTRADAY V3 — OBV T-Channel + RSI + MACD + Mom + ADX + EMA200."""
    if i < 2: return None
    oc = _get(ind, 'obv_oc', 'obv_macd_oc')
    if not oc or i >= len(oc): return None
    r = ind['rsi'][i]; mo = ind['mom'][i]; a = ind['adx'][i]
    ml = _get(ind, 'ml', 'macd')
    mc = ml[i] if ml else None
    e200 = ind['e200'][i]; close = ind['C'][i]
    if None in (r, mo, a, mc, e200): return None
    if a < 25:
        if ai_score < 75 or a < 20: return None

    is_buy  = oc[i] == 1  and r > 52 and mo > 0 and mc > 0 and close > e200
    is_sell = oc[i] == -1 and r < 48 and mo < 0 and mc < 0 and close < e200
    if is_buy:  return 'buy'
    if is_sell: return 'sell'
    return None


def signal_golden_squeeze(ind, i, h1_trend=None, hour=None):
    """S16: ELITE CONFLUENCE V2 — OBV Momentum + Trend Alignment (ST/h1_trend) + EMA 233."""
    if i < 233: return None
    # h1_trend: explicit H1 Supertrend value from bot; None → use ind['st'] proxy (backtester)
    if h1_trend is not None:
        st = h1_trend
    else:
        st_arr = ind.get('st')
        st = st_arr[i] if st_arr else 0
    if st == 0: return None

    obv_arr = ind.get('obv'); obv_ema_arr = ind.get('obv_ema')
    if obv_arr is None or obv_ema_arr is None: return None
    obv_val = obv_arr[i]; obv_ema = obv_ema_arr[i]
    c = ind['C'][i]; cp = ind['C'][i - 1]; e233 = ind['e233'][i]
    if None in (obv_val, obv_ema, e233): return None

    if st == -1:  # BULLISH
        if c > e233 and obv_val > obv_ema and c > cp: return 'buy'
    elif st == 1:  # BEARISH
        if c < e233 and obv_val < obv_ema and c < cp: return 'sell'
    return None


def signal_mfkk_scalping(ind, i, h1_trend=None, hour=None):
    """S09_MFKK_SCALPING V2 — EMA Fibonacci Stack (13,34,89,233) + FVG retest."""
    if i < 233: return None
    e13 = ind['e13'][i]; e34 = ind['e34'][i]; e89 = ind['e89'][i]; e233 = ind['e233'][i]
    fb = ind.get('fvg_bull'); fs = ind.get('fvg_bear')
    c = ind['C'][i]
    if None in (e13, e34, e89, e233) or fb is None: return None
    if e13 > e34 > e89 > e233 and c > e233 and fb[i]: return 'buy'
    if e13 < e34 < e89 < e233 and c < e233 and fs[i]: return 'sell'
    return None


def signal_ob_fvg_scalp(ind, i, h1_trend=None, hour=None):
    """S10_OB_FVG_SCALP V2 — ICT Order Block + FVG + EMA 233 Trend Filter."""
    if i < 233: return None
    ob_b = ind.get('ob_bull'); ob_s = ind.get('ob_bear')
    fb = ind.get('fvg_bull'); fs = ind.get('fvg_bear')
    e233 = ind['e233'][i]; c = ind['C'][i]
    if ob_b is None or fb is None or e233 is None: return None
    if ob_b[i] and fb[i] and c > e233: return 'buy'
    if ob_s[i] and fs[i] and c < e233: return 'sell'
    return None


def signal_convergence_scalp(ind, i, h1_trend=None, hour=None):
    """S17_CONVERGENCE_SCALP V2 — EMA 34/89 crossover + StochRSI + BB %B + EMA50."""
    if i < 89: return None
    e34 = ind['e34'][i]; e89 = ind['e89'][i]
    sk = ind['srsi_k'][i]; sd = ind['srsi_d'][i]
    bbu = ind['bb_up'][i]
    bbl_arr = _get(ind, 'bb_dn', 'bb_lo')
    bbl = bbl_arr[i] if bbl_arr else None
    c = ind['C'][i]; e50 = ind['e50'][i]; atr = ind['atr'][i]
    atr_ref = _get(ind, 'atr_avg', 'atr30')
    atr_avg = atr_ref[i] if atr_ref else None
    if None in (e34, e89, sk, sd, bbu, bbl, c, e50, atr): return None
    if atr_avg and atr > 2.2 * atr_avg: return None

    bb_range = bbu - bbl
    bb_pct = (c - bbl) / bb_range if bb_range > 0 else 0.5
    e34_p = ind['e34'][i - 1]; e89_p = ind['e89'][i - 1]
    sk_p = ind['srsi_k'][i - 1]; sd_p = ind['srsi_d'][i - 1]
    if None in (e34_p, e89_p, sk_p, sd_p): return None

    bull_prev = e34_p > e89_p and sk_p > sd_p
    bear_prev = e34_p < e89_p and sk_p < sd_p
    bull = e34 > e89 and sk > sd and bb_pct > 0.50 and c > e50 and not bull_prev
    bear = e34 < e89 and sk < sd and bb_pct < 0.50 and c < e50 and not bear_prev

    if bull: return 'buy'
    if bear: return 'sell'
    return None
