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

Optimization 2026-04-30 V5 (WR improvement pass):
  S05: ADX 15→18, RSI 54/46→57/43, RSI slope confirmation (r > r_prev)
  S09: ADX≥15 gate + RSI>50/<50 + OBV vs OBV_EMA volume confirmation
  S16: OBV slope 3→4 barre consecutive, DI spread esplicito ≥8
  S17: ADX 18→22, BB%B 0.55/0.45→0.62/0.38, candle direction filter
  S00: sell DI spread 20→25, sell_thr 72→76

Optimization 2026-04-30 V6 (S00 stop reduction):
  S00 BUY: DI+>=20 sempre obbligatorio (prima OR con ST) → WR 34.5%→36.7%, P&L +$1035 standalone
  S00 SELL: sessione 7-17h → 9-17h (7-9h in perdita -$371 su 58 trade)

S18_RANGE_REVERSAL V1 (2026-05-19):
  Mean-reversion per XAU/USD in RANGE/WEAK (ADX<22).
  Entry: prezzo all'estremo della BB (bb_pct<0.15 o >0.85) + RSI/WPR/StochRSI esausti + candela di inversione.
  TP: 2.0×ATR (verso BB middle), SL: 1.2×ATR. Session 7-19 UTC.

Optimization 2026-05-08 V6 S05 ultra-select (target WR≥35%, trade<80):
  S05: ADX 20→28, DI spread>=12 gate, RSI 57/43→62/38, session 7-17→9-15 UTC,
       ATR min gate (skip if ATR<0.8×avg), StochRSI K>60 (bull) / K<40 (bear).
  Rationale: WR 24-25% su 162+ trade → barely survive on R:R alone, not live-viable.
  Se post-backtest WR<35% con <50 trade → eliminare S05 dal rotation.
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

    # ADX gate: S00 richiede mercato con almeno una direzione minima (backtest: ADX<20 → WR cala -8pp)
    if a < 20: return None

    # DI spread gate: require at least minimal directional conviction
    if abs(dp - dm) < 5: return None

    # ── BUY: ST alignment + strong DI conviction filter ─────────────────────
    # Analysis (2026-04-28): BUY ST-aligned + DI≥20 → WR 28.3%, PF 1.38
    # Without ST filter all buys have WR 24.7%, PF 1.15 (fine but weaker)
    st_arr = ind.get('st')
    st_now = st_arr[i] if st_arr else 0
    buy_thr = 82 if (is_exh_buy or b_cross) else 90
    # BUY V6 (2026-04-30): DI+ conviction gate tf-dipendente.
    # M30: DI+>=20 obbligatorio (DI+<20 buys standalone WR 30.4% → tagliati)
    # H1/H4: DI+>=15 (H1 ha DI più compresso, soglia 20 taglia buone entrate +2.6pp WR)
    buy_di_spread = dp - dm
    buy_di_min    = 15 if tf in ('H1', 'H4') else 20
    buy_di_ok     = buy_di_spread >= buy_di_min
    if not buy_di_ok: buy_thr = 999  # blocca low-conviction buys indipendentemente da ST

    # ── SELL: sessione London+NY+early Asia (allargata 9-17 → 7-20 UTC) ────────
    # DI spread abbassato 25→18 e soglia 76→72 per recuperare setup validi
    # H4 SELL è inaffidabile (WR 17.5%) — bloccato su H4
    sell_thr = 999  # block by default
    is_london_ny = hour is not None and (7 <= hour < 20)
    sell_di_spread = dm - dp
    if tf != 'H4' and is_london_ny and sell_di_spread >= 18:
        sell_thr = 72

    if b_score >= buy_thr: return 'buy'
    if s_score >= sell_thr: return 'sell'

    return None


def signal_mfkk_intraday(ind, i, h1_trend=None, hour=None, ai_score=0):
    """S05_MFKK_INTRADAY V6 ultra-select — OBV T-Channel + RSI + MACD + Mom + ADX + EMA200 + ST.
    V4 (2026-04-28): ST alignment filter.
    V5 (2026-04-30): ADX 18→20, RSI 54/46→57/43, RSI slope.
    V6 (2026-05-08): ADX 20→28, DI spread>=12, RSI 57/43→62/38, session 9-15 UTC,
      ATR min gate (skip if ATR<0.8×avg), StochRSI absolute K>60/K<40 instead of K>D.
      Target: WR>=35% with <80 trade (from 24% on 162+). If still <35% → remove from rotation.
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

    # ADX gate — trend con direzionalità chiara (28→24: recupera WEAK strong entries)
    if a < 24: return None

    # DI spread gate — dominanza direzionale (12→8: meno restrittivo)
    dip_v = ind.get('dip', [None] * (i + 1))[i]
    dim_v = ind.get('dim', [None] * (i + 1))[i]
    if dip_v is not None and dim_v is not None:
        if abs(dip_v - dim_v) < 8: return None

    # Session filter: London+NY+Asia attiva (allargata 9-15 → 7-20 UTC)
    if hour is not None and not (7 <= hour < 20): return None

    # ATR range: skip flat bars e spike estremi
    atr_arr = ind.get('atr')
    atr_ref = _get(ind, 'atr_avg', 'atr30')
    atr_v = atr_arr[i] if atr_arr else None
    atr_avg_v = atr_ref[i] if atr_ref else None
    if atr_v and atr_avg_v:
        if atr_v < 0.8 * atr_avg_v: return None   # mercato troppo piatto
        if atr_v > 1.8 * atr_avg_v: return None   # spike news

    # Supertrend alignment: only trade in ST direction (V4)
    if h1_trend is not None and h1_trend != 0:
        if oc[i] == 1 and h1_trend != -1: return None
        if oc[i] == -1 and h1_trend != 1: return None

    # StochRSI assoluto: K>55 bull, K<45 bear (rilassato da K>60/K<40 per più trade)
    srsi_bull = (sk is None) or (sk > 55)
    srsi_bear = (sk is None) or (sk < 45)

    rp = ind['rsi'][i - 1] if i > 0 else r
    is_buy  = oc[i] == 1  and r > 58 and r > rp and mo > 0 and mc > 0 and close > e200 and srsi_bull
    is_sell = oc[i] == -1 and r < 42 and r < rp and mo < 0 and mc < 0 and close < e200 and srsi_bear
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

    # OBV 3-bar slope: sustained volume momentum (era 4 → troppo restrittivo, mancava inizio trend)
    obv_rising_3  = i >= 3 and obv_arr[i] > obv_arr[i-1] > obv_arr[i-2]
    obv_falling_3 = i >= 3 and obv_arr[i] < obv_arr[i-1] < obv_arr[i-2]

    if st == -1:  # BULLISH
        if dip_v - dim_v < 8: return None  # DI+ must dominate for BUY with spread ≥8
        if c > e233 and obv_val > obv_ema and obv_rising_3 and c > cp and big_enough:
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
        if c < e233 and obv_val < obv_ema and obv_falling_3 and c < cp and big_enough:
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

    # ADX gate: avoid dead-flat markets where FVG retests fail (alzato 15→20)
    a_arr = ind.get('adx')
    a = a_arr[i] if a_arr else None
    if a is not None and a < 20: return None

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
    """S10_OB_FVG_SCALP V4 — ICT Order Block + FVG + EMA 233 + ST alignment + ADX gate.
    V2: skip ATR spike (>2.5×avg).
    V3 (2026-04-28): Supertrend alignment + ADX>=18 gate.
    V4 (2026-06-03): Session filter 8-17 UTC — backtest fresco H1/M15 mostra WR 0% su 4 trade.
      OB/FVG invalidi fuori London+NY overlap: liquidità insufficiente per follow-through.
    """
    if i < 233: return None
    # Session filter: solo London+NY (8-17 UTC) — fuori da questa finestra WR cade a 0%
    if hour is not None and not (8 <= hour < 17): return None
    ob_b = ind.get('ob_bull'); ob_s = ind.get('ob_bear')
    fb = ind.get('fvg_bull'); fs = ind.get('fvg_bear')
    e233 = ind['e233'][i]; c = ind['C'][i]
    a = ind.get('adx', [None]*(i+1))[i]
    if ob_b is None or fb is None or e233 is None: return None

    # ADX gate: require at least minimal directional bias (alzato 18→20: H1 PF 0.896 → taglia ingressi deboli)
    if a is not None and a < 20: return None

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


def signal_range_reversal(ind, i, hour=None, **kwargs):
    """
    S18_RANGE_REVERSAL V1 — BB Band Exhaustion + RSI/WPR/StochRSI mean-reversion.
    Designed for XAU/USD RANGE/WEAK regime (ADX < 22).
    Entry: prezzo che rimbalza dall'estremo della BB con 3 oscillatori in esaurimento.
    Avoid: ATR spike (news), trend markets (ADX >= 22), sessione asiatica.
    M30 ottimale: TP 2.0×ATR verso BB midline, SL 1.2×ATR oltre la banda.
    """
    if i < 50: return None

    # Session: London + NY (7-19 UTC) — Asia ha liquidità insufficiente per reversal puliti
    if hour is not None and not (7 <= hour < 19): return None

    c  = ind['C'][i]
    cp = ind['C'][i - 1]

    bbu_arr = ind.get('bb_up')
    bbl_arr = _get(ind, 'bb_dn', 'bb_lo')
    bbu = bbu_arr[i] if bbu_arr else None
    bbl = bbl_arr[i] if bbl_arr else None
    if None in (c, cp, bbu, bbl): return None

    bb_range = bbu - bbl
    if bb_range <= 0: return None
    bb_pct = (c - bbl) / bb_range   # 0 = lower band, 1 = upper band

    # Gate 1: mercato laterale (ADX < 22)
    a_arr = ind.get('adx')
    a = a_arr[i] if a_arr else None
    if a is not None and a >= 22: return None

    # Gate 2: no ATR spike (news / evento estremo)
    atr_arr = ind.get('atr')
    atr_ref  = _get(ind, 'atr_avg', 'atr30')
    atr_v    = atr_arr[i] if atr_arr else None
    atr_avg  = atr_ref[i] if atr_ref else None
    if atr_v and atr_avg and atr_avg > 0 and atr_v > 1.8 * atr_avg: return None

    r_arr  = ind.get('rsi')
    wpr_arr = ind.get('wpr')
    sk_arr  = ind.get('srsi_k')
    r   = r_arr[i]  if r_arr  else None
    wpr_v = wpr_arr[i] if wpr_arr else None
    sk  = sk_arr[i] if sk_arr else None

    # BUY: prezzo all'estremo inferiore della BB + candela che chiude SOPRA il minimo precedente
    # (conferma inversione, non catching knife)
    if bb_pct <= 0.15 and c > cp:
        rsi_os  = r   is None or r   < 40
        wpr_os  = wpr_v is None or wpr_v < -70
        srsi_os = sk  is None or sk  < 30
        if rsi_os and wpr_os and srsi_os:
            return 'buy'

    # SELL: prezzo all'estremo superiore della BB + candela che chiude SOTTO il massimo precedente
    if bb_pct >= 0.85 and c < cp:
        rsi_ob  = r   is None or r   > 60
        wpr_ob  = wpr_v is None or wpr_v > -30
        srsi_ob = sk  is None or sk  > 70
        if rsi_ob and wpr_ob and srsi_ob:
            return 'sell'

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


# ─────────────────────────────────────────────────────────────────────────────
# S20_FIB_CONFLUENCE V2 "config di principio" (2026-08-28)
#
# Port + tuning della strategia scalping "Repro Overlay — M5". 4 iterazioni di
# ricerca (research/s20_fib_confluence/RESULTS.md): il port fedele perde; questa
# è l'unica config con edge OOS reale — full-period PF 1.54, OOS ultimi 8 mesi
# PF 1.72 (n=54), walk-forward per terzi 1.16/1.23/1.79, BUY e SELL entrambi
# positivi. LIVE da 2026-08-28 a lotto fisso 0.03 (isolata, fuori da Strategy
# Selector / compounding). Vedi 04_bot_operations.md § S20.
#
#   Setup (bar j, poi conferma al bar j+1):
#     zona estremo 20b (entro il 25% del range) + candela di inversione
#     + prezzo oltre Fib 0.382/0.618 (swing 50) + ribbon EMA20/50 allineato
#   Ingresso al bar j+1 SOLO se conferma la direzione (close j+1 vs close j)
#   Struttura: higher-low (buy) / lower-high (sell) — finestra 10 vs 35 barre
#   Trend HTF: close vs EMA200 (sul TF stesso, M5 ≈ ~16h di contesto)
#   SL strutturale: min(low_candela − 0.15·ATR, entry − 1.5·ATR)   [simm. per SELL]
#   TP1 = 1R  ·  TP2 = 2R    (gestione a parziali: chiudi a TP1, resto a BE→TP2)
#   Sessione core London+NY overlap 8–17 UTC · NIENTE lunedì (rumore da gap weekend)
# ─────────────────────────────────────────────────────────────────────────────

FIB_SWING_LB     = 50        # lookback swing per i livelli Fibonacci
FIB_SIG_LB       = 20        # lookback estremi per il trigger
FIB_SESSION      = (8, 17)   # core London+NY overlap (UTC) — sweep 2026-09-02: holdout PF M5 2.37->2.78, M15 1.17->1.58, M30 1.57->3.67; full DD M5 -19%
FIB_BAND         = 0.25      # "zona estremo" = entro il 25% del range 20-barre
FIB_STRUCT_NEAR  = 10        # finestra swing recente (higher-low / lower-high)
FIB_STRUCT_FAR   = 35        # finestra swing precedente
FIB_SL_ATR_K     = 1.5       # SL non più stretto di k·ATR
FIB_SL_BUF       = 0.15      # buffer oltre il minimo/massimo della candela-segnale (·ATR)
FIB_TP1_R        = 1.0       # TP1 in multipli di R
FIB_TP2_R        = 2.0       # TP2 (runner) in multipli di R
FIB_NO_MONDAY    = True      # niente lunedì (rumore da gap weekend)


def fib_confluence_levels(ind, i, swing=FIB_SWING_LB):
    """Livelli Fibonacci sullo swing delle ultime `swing` barre fino a i incluso.
    Ritorna dict {hi, lo, rng, l236, l382, l500, l618, l786} o None se non calcolabile."""
    if i < swing:
        return None
    H = ind['H']; L = ind['L']
    seg_hi = max(H[i - swing + 1:i + 1])
    seg_lo = min(L[i - swing + 1:i + 1])
    rng = seg_hi - seg_lo
    if rng <= 0:
        return None
    return {
        'hi': seg_hi, 'lo': seg_lo, 'rng': rng,
        'l236': seg_lo + rng * 0.236,
        'l382': seg_lo + rng * 0.382,
        'l500': seg_lo + rng * 0.500,
        'l618': seg_lo + rng * 0.618,
        'l786': seg_lo + rng * 0.786,
    }


def _fib_raw_conf(ind, j):
    """(buy_conf, sell_conf) grezzi al bar j: zona estremo + candela inversione + Fib + ribbon.
    Nessun edge-trigger, nessuna struttura. (False, False) se dati mancanti."""
    if j < max(FIB_SWING_LB, FIB_SIG_LB):
        return (False, False)
    H = ind['H']; L = ind['L']; C = ind['C']; O = ind['O']
    c = C[j]; o = O[j]
    e20 = ind['e20'][j]; e50 = ind['e50'][j]
    if None in (c, o, e20, e50):
        return (False, False)
    lv = fib_confluence_levels(ind, j)
    if lv is None:
        return (False, False)
    rib_bull = e20 >= e50
    hi20 = max(H[j - FIB_SIG_LB + 1:j + 1])
    lo20 = min(L[j - FIB_SIG_LB + 1:j + 1])
    band = (hi20 - lo20) * FIB_BAND
    is_bot = L[j] <= lo20 + band and c > o
    is_top = H[j] >= hi20 - band and c < o
    buy_conf  = is_bot and c < lv['l382'] and rib_bull
    sell_conf = is_top and c > lv['l618'] and not rib_bull
    return (buy_conf, sell_conf)


def _fib_struct_ok(ind, i, direction):
    """higher-low (buy) / lower-high (sell): il pullback deve tenere sopra/sotto lo swing precedente."""
    H = ind['H']; L = ind['L']
    if i < FIB_STRUCT_FAR + 1:
        return False
    if direction == 'buy':
        recent_low = min(L[i - FIB_STRUCT_NEAR + 1:i + 1])
        prior_low  = min(L[i - FIB_STRUCT_FAR:i - FIB_STRUCT_NEAR])
        return recent_low > prior_low
    recent_high = max(H[i - FIB_STRUCT_NEAR + 1:i + 1])
    prior_high  = max(H[i - FIB_STRUCT_FAR:i - FIB_STRUCT_NEAR])
    return recent_high < prior_high


def fib_confluence_trade_levels(ind, i, direction):
    """SL / TP1 / TP2 assoluti per un trade S20 al bar i (SL strutturale + floor ATR, TP 1R/2R).
    Ritorna None se non calcolabile (ATR mancante / geometria invalida)."""
    entry = ind['C'][i]
    atr = ind['atr'][i]
    if entry is None or not atr or atr <= 0:
        return None
    L = ind['L']; H = ind['H']
    buf = FIB_SL_BUF * atr
    if direction == 'buy':
        sl = min(L[i] - buf, entry - FIB_SL_ATR_K * atr)
        risk = entry - sl
        if risk <= 0:
            return None
        return {'sl': sl, 'tp1': entry + risk * FIB_TP1_R, 'tp2': entry + risk * FIB_TP2_R, 'risk': risk}
    sl = max(H[i] + buf, entry + FIB_SL_ATR_K * atr)
    risk = sl - entry
    if risk <= 0:
        return None
    return {'sl': sl, 'tp1': entry - risk * FIB_TP1_R, 'tp2': entry - risk * FIB_TP2_R, 'risk': risk}


def signal_fib_confluence(ind, i, h1_trend=None, hour=None, weekday=None):
    """S20_FIB_CONFLUENCE V2 — vedi blocco commento sopra.
    Ritorna 'buy' | 'sell' | None. Livelli SL/TP via fib_confluence_trade_levels(ind, i, dir)."""
    if i < max(FIB_SWING_LB, FIB_SIG_LB) + 3:
        return None
    if hour is not None and not (FIB_SESSION[0] <= hour < FIB_SESSION[1]):
        return None
    if weekday is not None and FIB_NO_MONDAY and weekday == 0:   # niente lunedì
        return None

    buy_setup, sell_setup = _fib_raw_conf(ind, i - 1)  # setup alla barra precedente
    C = ind['C']
    if C[i] is None or C[i - 1] is None:
        return None
    if buy_setup and C[i] > C[i - 1]:                  # bar i conferma verso l'alto
        direction = 'buy'
    elif sell_setup and C[i] < C[i - 1]:               # bar i conferma verso il basso
        direction = 'sell'
    else:
        return None

    if not _fib_struct_ok(ind, i, direction):
        return None

    # filtro trend HTF: solo pullback in trend
    c = C[i]; e200 = ind['e200'][i]
    if e200 is None:
        return None
    if direction == 'buy' and not c > e200:
        return None
    if direction == 'sell' and not c < e200:
        return None

    # i livelli devono essere calcolabili (ATR presente, geometria valida)
    if fib_confluence_trade_levels(ind, i, direction) is None:
        return None

    return direction


# ═══════════════════════════════════════════════════════════════════════════════
# S30_DOW_DIP — mean-reversion azionaria (US30 / Dow), LONG-ONLY, TF H4
# ─────────────────────────────────────────────────────────────────────────────
#   "Compra la debolezza nella forza" (Connors RSI(2)). È l'edge indici più
#   duraturo: gli indici sovra-reagiscono nel breve e rimbalzano verso la media
#   finché il trend primario regge. Long-only: l'equity risk premium fa driftare
#   gli indici al rialzo → lo short-mean-reversion non ha lo stesso edge.
#   Ricerca: scripts/us30_harness.py — full PF 1.63 / holdout PF 2.09 / 4-4 fold WF.
#   Exit (gestito dal chiamante): TP DOW_DIP_TP_ATR·ATR, SL DOW_DIP_SL_ATR·ATR,
#   NESSUN trailing, time-stop dopo DOW_DIP_MAX_BARS barre H4.
# ═══════════════════════════════════════════════════════════════════════════════

DOW_DIP_RSI_LEN      = 2       # RSI ultra-breve (Connors)
DOW_DIP_RSI_BUY      = 15      # soglia oversold
DOW_DIP_DOWN_CLOSES  = 2       # chiusure H4 consecutive in calo richieste
DOW_DIP_REGIME_SLOPE = 20      # barre per la pendenza EMA50 (trend primario vivo)
DOW_DIP_MAX_BELOW_HI = 0.08    # max distanza dal massimo di 50 barre (è un dip, non un bear market)
DOW_DIP_TP_ATR       = 1.2     # TP = k·ATR (snap-back veloce)
DOW_DIP_SL_ATR       = 2.6     # SL = k·ATR (largo: le entry mean-rev peggiorano prima di migliorare)
DOW_DIP_MAX_BARS     = 18      # time-stop in barre H4 (~3 giorni)


def _rsi_wilder_n(C, i, n):
    """RSI di Wilder su n periodi calcolato al bar i (per RSI(2)/RSI(3))."""
    if i <= n:
        return None
    gains = 0.0
    losses = 0.0
    for k in range(i - n + 1, i + 1):
        ch = C[k] - C[k - 1]
        if ch >= 0:
            gains += ch
        else:
            losses -= ch
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100.0 - 100.0 / (1.0 + rs)


def signal_dow_dip(ind, i, hour=None, **kwargs):
    """S30_DOW_DIP — ritorna 'buy' | None (long-only). TF atteso: H4.
    Richiede in `ind`: C, e50, e233 (o e200 come fallback), atr."""
    C = ind['C']
    e50 = _get(ind, 'e50')
    e233 = _get(ind, 'e233', 'e200')
    if C is None or e50 is None or e233 is None:
        return None
    if i < 60 or e50[i] is None or e233[i] is None or e50[i - DOW_DIP_REGIME_SLOPE] is None:
        return None
    r = _rsi_wilder_n(C, i, DOW_DIP_RSI_LEN)
    if r is None or r >= DOW_DIP_RSI_BUY:
        return None
    # N chiusure consecutive in calo
    for k in range(DOW_DIP_DOWN_CLOSES):
        if not (C[i - k] < C[i - k - 1]):
            return None
    hi50 = max(C[i - 50:i + 1])
    if hi50 <= 0:
        return None
    regime_ok = (C[i] > e233[i]
                 and e50[i] > e50[i - DOW_DIP_REGIME_SLOPE]
                 and (hi50 - C[i]) / hi50 < DOW_DIP_MAX_BELOW_HI)
    if C[i] > e50[i] and regime_ok:
        return 'buy'
    return None


def signal_ema_trend_confluence(ind, i, hour=None, **kwargs):
    """S21_EMA_TREND_CONFLUENCE V1 (2026-09-07) — ipotesi generata da feature_screen.py
    (ML feature screening, skill signal-classification): su XAU H1 le feature con maggior
    permutation importance out-of-sample (AUC holdout 0.579) erano distanza da EMA233/200/100
    (contesto trend lungo), ADX, StochRSI K/D (timing), MACD histogram (momentum) — vedi
    directives/02_strategies.md 2026-09-07. TRIX/Donchian/MFI/Choppiness/Elder Ray (altre
    feature top) NON sono ancora nel pipeline live (solo in extra_indicators.py, research-only)
    — v1 usa solo indicatori già in compute_all()/compute_indicators(), niente promozione
    di nuovi indicatori nel path live per ora.

    Entry: prezzo sopra (buy) / sotto (sell) EMA233+EMA200+EMA100 (allineamento trend lungo)
    + ADX>=20 (evita mercati choppy) + DI dominance + MACD histogram concorde + StochRSI K
    che incrocia D nella direzione del trade (timing pullback), K non ancora ipercomprato/ipervenduto.

    TESTATA 2026-09-07 con opt_harness.py, grid tp/sl (7 trial, vedi research_trials.json):
    full-period PF<1 su TUTTE le configurazioni testate (0.66-0.89) — l'AUC 0.579 del
    classificatore NON si è tradotto in un edge reale una volta discretizzato in regole
    esplicite. L'holdout mostrava occasionalmente PF>1 (es. tp2.5/sl1.25 → holdout PF 1.914)
    ma con n=18 trade e full-period negativo è quasi certamente rumore, non edge — stesso
    pattern già visto oggi su S10_OB_FVG_SCALP. NON PROMOSSA, NON wired in STRATEGIES_CONFIG/
    PLAYBOOK. Tenuta come record storico dell'ipotesi (vedi directives/02_strategies.md).
    Ipotesi per v2 (non fatta): il crossing StochRSI K/D scarta troppa informazione del
    classificatore — provare un trigger meno rigido, o promuovere TRIX/Choppiness/MFI da
    extra_indicators.py nel path live invece di limitarsi ai soli indicatori già esistenti.
    """
    if i < 233:
        return None
    if hour is not None and not (7 <= hour < 18):
        return None

    C = ind['C']
    e233 = _get(ind, 'e233'); e200 = _get(ind, 'e200'); e100 = _get(ind, 'e100')
    adx_arr = _get(ind, 'adx'); dip_arr = _get(ind, 'dip'); dim_arr = _get(ind, 'dim')
    macd_hist = _get(ind, 'macd_hist', 'mh')
    srsi_k = _get(ind, 'srsi_k'); srsi_d = _get(ind, 'srsi_d')
    if None in (e233, e200, e100, adx_arr, dip_arr, dim_arr, macd_hist, srsi_k, srsi_d):
        return None

    c = C[i]
    e233_v, e200_v, e100_v = e233[i], e200[i], e100[i]
    adx_v, dip_v, dim_v = adx_arr[i], dip_arr[i], dim_arr[i]
    mh_v = macd_hist[i]
    k_v, d_v = srsi_k[i], srsi_d[i]
    k_prev, d_prev = srsi_k[i - 1], srsi_d[i - 1]
    if None in (e233_v, e200_v, e100_v, adx_v, dip_v, dim_v, mh_v, k_v, d_v, k_prev, d_prev):
        return None
    if adx_v < 20:
        return None

    trend_up = c > e233_v and c > e200_v and c > e100_v
    trend_down = c < e233_v and c < e200_v and c < e100_v

    if trend_up and dip_v > dim_v and mh_v > 0:
        k_cross_up = k_prev <= d_prev and k_v > d_v and k_v < 75
        if k_cross_up:
            return 'buy'
    elif trend_down and dim_v > dip_v and mh_v < 0:
        k_cross_down = k_prev >= d_prev and k_v < d_v and k_v > 25
        if k_cross_down:
            return 'sell'
    return None


def signal_trix_chop_confluence(ind, i, hour=None, **kwargs):
    """S22_TRIX_CHOP_CONFLUENCE V1 (2026-09-07) — seconda ipotesi da feature_screen.py,
    "seconda strada" rispetto a S21: invece di irrigidire ulteriormente EMA+StochRSI-cross,
    promuove TRIX/Choppiness Index/MFI (skill ta-lib/regime-detection, prima solo in
    extra_indicators.py research-only) nel path live — vedi compute_all()/compute_indicators()
    2026-09-07 — e li usa come filtro PRINCIPALE al posto del trigger discreto StochRSI K/D
    (S21 lezione: un crossing binario butta via informazione, qui TRIX>0/crescente è un
    trigger continuo più morbido).

    Entry: Choppiness Index < 38.2 (soglia standard "mercato in trend", non range) + prezzo
    sopra/sotto EMA233 (contesto trend lungo, unico filtro tenuto da S21) + TRIX concorde e
    in crescita/calo (momentum, non un cross discreto) + MFI in fascia utile (non ipercomprato/
    ipervenduto) + ADX>=18 (più permissivo di S21 — la Choppiness già filtra il range).

    TESTATA 2026-09-07 con opt_harness.py (13 trial totali, vedi research_trials.json):
    full-period PF<1 su TUTTE le 13 configurazioni testate (0.52-0.77), sia full che holdout —
    a differenza di S21 qui nemmeno l'holdout mostra un falso positivo isolato, rigetto netto.
    Aggiunto un filtro di dominanza DI (+DI/-DI) come tentativo di affinamento: risultati
    IDENTICI alla v1 senza quel filtro — era già implicito nelle altre condizioni, non la
    causa del problema. Il problema è la selettività complessiva del setup (Choppiness<38.2 +
    TRIX rising + banda MFI lascia passare troppi trade marginali, ~3.1 trade/giorno a bassa
    qualità). NON PROMOSSA, NON wired in STRATEGIES_CONFIG/PLAYBOOK.
    """
    if i < 233:
        return None
    if hour is not None and not (7 <= hour < 18):
        return None

    C = ind['C']
    e233 = _get(ind, 'e233')
    adx_arr = _get(ind, 'adx')
    dip_arr = _get(ind, 'dip'); dim_arr = _get(ind, 'dim')
    trix_arr = _get(ind, 'trix')
    chop_arr = _get(ind, 'choppiness')
    mfi_arr = _get(ind, 'mfi')
    if None in (e233, adx_arr, dip_arr, dim_arr, trix_arr, chop_arr, mfi_arr):
        return None

    c = C[i]
    e233_v = e233[i]
    adx_v = adx_arr[i]
    dip_v, dim_v = dip_arr[i], dim_arr[i]
    trix_v, trix_prev = trix_arr[i], trix_arr[i - 1]
    chop_v = chop_arr[i]
    mfi_v = mfi_arr[i]
    if None in (e233_v, adx_v, dip_v, dim_v, trix_v, trix_prev, chop_v, mfi_v):
        return None
    if adx_v < 18 or chop_v >= 38.2:
        return None

    trend_up = c > e233_v
    trend_down = c < e233_v

    if trend_up and dip_v > dim_v and trix_v > 0 and trix_v > trix_prev and 40 <= mfi_v <= 80:
        return 'buy'
    if trend_down and dim_v > dip_v and trix_v < 0 and trix_v < trix_prev and 20 <= mfi_v <= 60:
        return 'sell'
    return None


# ─────────────────────────────────────────────────────────────────────────────
# LAYOUT-COMBO STRATEGIES (2026-09-10) — dai layout TradingView XAU_M15/M30/H1
#
# I layout XAU_* (tutti tranne MFKK_GOLD, che è già S00) condividono lo stesso
# toolkit discrezionale:
#   • Trendlines with Breaks [LuxAlgo]   (length 14, slope ATR×1)  → tlb_up/tlb_dn
#   • Pivot Points Standard (Fibonacci, daily)                     → dpiv/dr1..3/ds1..3
#   • Key Levels SpacemanBTC IDWM (PDH/PDL, PWH/PWL)               → pdh/pdl/pwh/pwl
#   • Moving Average Exponential 200 (close)                       → ema200
#   • Sessions [LuxAlgo] (London 07-16, NY 12-21 UTC)             → filtro hour
# Tutti gli array sono prodotti da compute_all() (strategy-engine-v2.py).
# BE + trailing sono applicati dal backtester (run_one) — non qui.
#
# Parametri tunabili raccolti in TLB_* / PIV_* per gli sweep opt_harness.
# ─────────────────────────────────────────────────────────────────────────────

TLB_SESSION       = (7, 20)   # London open → NY close (UTC)
TLB_ADX_MIN       = 18        # gate direzionalità minima sul break
PIV_SESSION       = (7, 19)
PIV_TOL_ATR       = 0.35      # "tocco" di un livello = entro k·ATR
PIV_REV_RSI_BUY   = 45        # RSI massimo per un buy di reversione
PIV_REV_RSI_SELL  = 55        # RSI minimo per un sell di reversione


def signal_tlb_trend(ind, i, hour=None, **kwargs):
    """SA_TLB_TREND — LuxAlgo Trendline Break in direzione del trend EMA200, in sessione.
    Combo: Trendlines with Breaks + Moving Average Exponential(200) + Sessions.
    Trend-following: si entra sulla barra in cui il prezzo rompe la trendline
    (discendente per un buy, ascendente per un sell) solo se è dal lato "giusto"
    dell'EMA200 e con ADX minimo.
    """
    s0, s1 = kwargs.get('session', TLB_SESSION)
    if i < 260:
        return None
    if hour is not None and not (s0 <= hour < s1):
        return None
    up = ind.get('tlb_up'); dn = ind.get('tlb_dn')
    ema200 = ind.get('ema200')
    if up is None or dn is None or ema200 is None:
        return None
    e = ema200[i]; c = ind['C'][i]
    if e is None:
        return None
    adx_min = kwargs.get('adx_min', TLB_ADX_MIN)
    a_arr = ind.get('adx'); a = a_arr[i] if a_arr else None
    if a is not None and a < adx_min:
        return None
    use_ema = kwargs.get('use_ema', True)
    fade = kwargs.get('fade', False)
    if kwargs.get('strict', False):
        up = ind.get('tlb_up_s', up); dn = ind.get('tlb_dn_s', dn)
    if fade:
        # fade: shorta un up-break che avviene SOTTO l'EMA200 (probabile falso breakout)
        if up[i] and (not use_ema or c < e):
            return 'sell'
        if dn[i] and (not use_ema or c > e):
            return 'buy'
        return None
    if up[i] and (not use_ema or c > e):
        return 'buy'
    if dn[i] and (not use_ema or c < e):
        return 'sell'
    return None


def _recent_cross(arr, C, i, lb, up):
    """True se il prezzo ha attraversato `arr` (livello) nella direzione `up`
    nelle ultime `lb` barre (close da un lato a close dall'altro)."""
    if arr is None:
        return False
    for j in range(max(1, i - lb), i + 1):
        lv = arr[j]
        if lv is None or arr[j-1] is None:
            continue
        if up and C[j-1] <= lv < C[j]:
            return True
        if (not up) and C[j-1] >= lv > C[j]:
            return True
    return False


def signal_tlb_confluence(ind, i, hour=None, **kwargs):
    """SD_TLB_CONFLUENCE — la "tesi" vera dei layout: si entra SOLO quando più cose
    si allineano. Trendline break (stretto) + il prezzo ha appena attraversato un
    livello Fib pivot nella stessa direzione + EMA200 concorde + sessione London/NY.
    Poche entrate, per costruzione."""
    s0, s1 = kwargs.get('session', (7, 20))
    if i < 300:
        return None
    if hour is not None and not (s0 <= hour < s1):
        return None
    C = ind['C']; c = C[i]
    ema200 = ind.get('ema200')
    up = ind.get('tlb_up_s'); dn = ind.get('tlb_dn_s')
    if ema200 is None or up is None or ema200[i] is None:
        return None
    e = ema200[i]
    atr = ind['atr'][i]
    if not atr:
        return None
    a_arr = ind.get('adx'); a = a_arr[i] if a_arr else None
    if a is not None and a < kwargs.get('adx_min', 18):
        return None
    lb = kwargs.get('cross_lb', 3)
    pivot_keys = kwargs.get('pivot_keys', ('dpiv', 'dr1', 'ds1'))
    piv_up = any(_recent_cross(ind.get(k), C, i, lb, True) for k in pivot_keys)
    piv_dn = any(_recent_cross(ind.get(k), C, i, lb, False) for k in pivot_keys)
    if up[i] and c > e and piv_up:
        return 'buy'
    if dn[i] and c < e and piv_dn:
        return 'sell'
    return None


def signal_pivot_bias_pullback(ind, i, hour=None, **kwargs):
    """SE_PIVOT_PULLBACK — bias dal pivot giornaliero + EMA200, ingresso sul RITRACCIAMENTO.
    Bias long: close > P (pivot) e close > EMA200. In quel bias si compra un pullback
    che tocca S1 (o l'EMA200) e stampa una candela di inversione rialzista. Mirror per short.
    Non è un breakout — si entra CONTRO il movimento di breve, con il trend di fondo."""
    s0, s1 = kwargs.get('session', (7, 19))
    if i < 300:
        return None
    if hour is not None and not (s0 <= hour < s1):
        return None
    C = ind['C']; H = ind['H']; L = ind['L']; O = ind['O']
    c = C[i]; cp = C[i-1]; op = O[i]; lo = L[i]; hi = H[i]
    e_arr = ind.get('ema200'); p_arr = ind.get('dpiv')
    if e_arr is None or p_arr is None or e_arr[i] is None or p_arr[i] is None:
        return None
    e = e_arr[i]; p = p_arr[i]
    atr = ind['atr'][i]
    if not atr:
        return None
    tol = kwargs.get('tol_atr', 0.4) * atr
    s1_arr = ind.get('ds1'); r1_arr = ind.get('dr1')
    rev_bull = c > op and c > cp                 # candela verde che chiude sopra la precedente
    rev_bear = c < op and c < cp
    if c > p and c > e:                          # bias long
        pull_targets = [x for x in (s1_arr[i] if s1_arr else None, e) if x is not None]
        if any(lo <= t + tol and c > t for t in pull_targets) and rev_bull:
            return 'buy'
    if c < p and c < e:                          # bias short
        pull_targets = [x for x in (r1_arr[i] if r1_arr else None, e) if x is not None]
        if any(hi >= t - tol and c < t for t in pull_targets) and rev_bear:
            return 'sell'
    return None


def signal_session_range_break(ind, i, hour=None, weekday=None, **kwargs):
    """SF_SESSION_ORB — opening-range breakout della sessione di Londra.
    Le prime `or_bars` barre dopo l'apertura Londra (07:00 UTC) definiscono un range;
    una chiusura oltre l'estremo del range, nella direzione del bias pivot, entra.
    Un solo trade per sessione (gestito dal cooldown/MAX_TRADES del backtester)."""
    if i < 300 or hour is None:
        return None
    or_bars = kwargs.get('or_bars', 4)
    tf_min = kwargs.get('tf_min', 60)
    open_hour = kwargs.get('open_hour', 7)
    # quante barre servono per coprire l'opening range e quante ne restano nella sessione
    span = or_bars
    if not (open_hour <= hour < open_hour + kwargs.get('window_h', 6)):
        return None
    C = ind['C']; H = ind['H']; L = ind['L']
    import datetime as _dt
    # trova l'indice della prima barra della sessione odierna
    def _h(j): return _dt.datetime.utcfromtimestamp(ind['T'][j]).hour if ind.get('T') else None
    T = ind.get('T')
    if T is None:
        return None
    day0 = _dt.datetime.utcfromtimestamp(T[i]).date()
    start = None
    for j in range(i, max(0, i - 40), -1):
        dj = _dt.datetime.utcfromtimestamp(T[j])
        if dj.date() != day0:
            break
        if dj.hour < open_hour:
            break
        start = j
    if start is None or i - start < span:
        return None
    orh = max(H[start:start + span]); orl = min(L[start:start + span])
    if i < start + span:
        return None
    c = C[i]; cp = C[i-1]
    e_arr = ind.get('ema200'); p_arr = ind.get('dpiv')
    e = e_arr[i] if e_arr else None
    p = p_arr[i] if p_arr else None
    atr = ind['atr'][i]
    if not atr:
        return None
    margin = kwargs.get('margin_atr', 0.1) * atr
    long_bias = (p is None or c > p) and (e is None or c > e)
    short_bias = (p is None or c < p) and (e is None or c < e)
    if cp <= orh and c > orh + margin and long_bias:
        return 'buy'
    if cp >= orl and c < orl - margin and short_bias:
        return 'sell'
    return None


def _piv_levels(ind, i, keys):
    out = []
    for k in keys:
        arr = ind.get(k)
        if arr is not None and arr[i] is not None:
            out.append(arr[i])
    return out


def signal_pivot_reversal(ind, i, hour=None, **kwargs):
    """SB_PIVOT_REV — rifiuto di un livello Fib pivot o key level (PDH/PDL/PWH/PWL).
    Combo: Pivot Points Standard (Fibonacci) + Key Levels SpacemanBTC + Sessions.
    Mean-reversion: la barra buca il livello con la mecca (wick) ma chiude dal lato
    opposto, chiusura contro la barra precedente, oscillatore RSI esausto.
    """
    s0, s1 = kwargs.get('session', PIV_SESSION)
    if i < 260:
        return None
    if hour is not None and not (s0 <= hour < s1):
        return None
    C = ind['C']; H = ind['H']; L = ind['L']; O = ind['O']
    c = C[i]; hi = H[i]; lo = L[i]; op = O[i]
    atr = ind['atr'][i]
    if not atr or atr <= 0:
        return None
    atr_avg = ind['atr30'][i]
    if atr_avg and atr > kwargs.get('spike_k', 1.8) * atr_avg:
        return None                                        # no news spike
    a_arr = ind.get('adx'); a = a_arr[i] if a_arr else None
    if a is not None and a >= kwargs.get('adx_max', 24):
        return None                                        # solo range / weak-trend
    tol = kwargs.get('tol_atr', PIV_TOL_ATR) * atr
    wick_min = kwargs.get('wick_atr', 0.30) * atr
    r_arr = ind.get('rsi'); r = r_arr[i] if r_arr else None
    rsi_buy = kwargs.get('rsi_buy', PIV_REV_RSI_BUY)
    rsi_sell = kwargs.get('rsi_sell', PIV_REV_RSI_SELL)
    res = [x for x in _piv_levels(ind, i, ('dr1', 'dr2', 'dr3', 'pdh', 'pwh')) if x >= c]
    sup = [x for x in _piv_levels(ind, i, ('ds1', 'ds2', 'ds3', 'pdl', 'pwl')) if x <= c]
    lvl_r = min(res) if res else None                      # solo il livello più vicino
    lvl_s = max(sup) if sup else None
    if lvl_r is not None:
        upper_wick = hi - max(c, op)
        if (hi >= lvl_r - tol and c < lvl_r and c < op
                and upper_wick >= wick_min and (r is None or r > rsi_sell)):
            return 'sell'
    if lvl_s is not None:
        lower_wick = min(c, op) - lo
        if (lo <= lvl_s + tol and c > lvl_s and c > op
                and lower_wick >= wick_min and (r is None or r < rsi_buy)):
            return 'buy'
    return None


def signal_pivot_break(ind, i, hour=None, **kwargs):
    """SC_PIVOT_BREAK — breakout di continuazione oltre un livello Fib pivot.
    Combo: Pivot Points Standard + Moving Average Exponential(200) + Trendlines with Breaks.
    La barra chiude oltre il livello (P / R1 / R2 per un buy; P / S1 / S2 per un sell),
    dal lato giusto dell'EMA200; opzionale conferma di un trendline break concorde.
    """
    s0, s1 = kwargs.get('session', PIV_SESSION)
    if i < 260:
        return None
    if hour is not None and not (s0 <= hour < s1):
        return None
    C = ind['C']; c = C[i]; cp = C[i-1]
    ema200 = ind.get('ema200')
    if ema200 is None or ema200[i] is None:
        return None
    e = ema200[i]
    atr = ind['atr'][i]
    if not atr:
        return None
    atr_avg = ind['atr30'][i]
    if atr_avg and atr > kwargs.get('spike_k', 2.2) * atr_avg:
        return None
    a_arr = ind.get('adx'); a = a_arr[i] if a_arr else None
    if a is not None and a < kwargs.get('adx_min', 20):
        return None                                        # breakout ha bisogno di trend
    margin = kwargs.get('margin_atr', 0.15) * atr
    approach = kwargs.get('approach_bars', 6)
    need_tlb = kwargs.get('need_tlb', False)
    up = ind.get('tlb_up'); dn = ind.get('tlb_dn')
    ups = _piv_levels(ind, i, ('dpiv', 'dr1', 'dr2', 'pdh'))
    dns = _piv_levels(ind, i, ('dpiv', 'ds1', 'ds2', 'pdl'))
    for lvl in ups:
        if (cp < lvl and c > lvl + margin and c > e
                and all(C[j] < lvl for j in range(i - approach, i))
                and (not need_tlb or (up and up[i]))):
            return 'buy'
    for lvl in dns:
        if (cp > lvl and c < lvl - margin and c < e
                and all(C[j] > lvl for j in range(i - approach, i))
                and (not need_tlb or (dn and dn[i]))):
            return 'sell'
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# S31_LAYOUT_SMART — break → retest → confluenza (2026-09-10)
# ═══════════════════════════════════════════════════════════════════════════════
# Come si trada DAVVERO il toolkit dei layout TradingView XAU_* (non "compra ogni
# rottura"):
#   REGIME  : solo trend pulito — EMA200 in pendenza (slope >= k*ATR su N barre) e
#             prezzo dal lato giusto. In range/chop non si opera.
#   TRIGGER : rottura di una trendline LuxAlgo (stretta, close oltre la linea) nel
#             verso del trend -> si MEMORIZZA il livello rotto, non si entra.
#   RETEST  : nelle K barre il prezzo torna su una ZONA DI CONFLUENZA (>= min_lv
#             livelli tra Fib pivot / PDH-PDL-PWH-PWL / H-L sessioni / prev-4H /
#             EMA200 / trendline, raggruppati entro band*ATR) vicina al livello rotto.
#   ENTRY   : candela di rifiuto alla zona (mecca >= w*ATR, chiusura ricentrata);
#             opzionale conferma di volume (layout XAU_H1_Volumes).
#   STOP    : strutturale, oltre la zona / lo swing del rifiuto, cap a stop_max*ATR.
#   TARGET  : TP1 fisso 1.5R (parziale 50%) -> BE -> trailing dietro la TRENDLINE ->
#             runner a TP2 (zona di confluenza successiva o 3R).
#
# Backtest (H1, 22 mesi, cost model ON, 0.01 lot): full PF 1.99 - +$516 - DD $130 -
# 16/22 mesi+ - holdout PF 1.86 - live-window PF 1.66 - walk-forward 3/4 fold+ -
# PBO 0.33 (non overfit) - regge spread x2 - buy+sell entrambi positivi. n=53
# (sottile). M30 PBO 0.53 (overfit), M15 morto -> SOLO H1.
#
# layout_smart.py (backtest) e mt5-bot.py (blocco _ls_*) usano ENTRAMBI queste
# funzioni -- nessuna logica duplicata (regola CLAUDE.md).

LS_LEVEL_KEYS = ('dpiv', 'dr1', 'dr2', 'dr3', 'ds1', 'ds2', 'ds3', 'pdh', 'pdl', 'pwh', 'pwl',
                 'ema200', 'sess_asia_hi', 'sess_asia_lo', 'sess_lon_hi', 'sess_lon_lo',
                 'sess_ny_hi', 'sess_ny_lo', 'p4h_hi', 'p4h_lo', 'day_open',
                 'tlb_upper', 'tlb_lower')

LS_PARAMS = dict(
    slope_bars=10, slope_min=0.12, retest_min=1, retest_max=16,
    band=0.55, min_lv=2, retest_tol=0.35, reject_wick=0.22,
    stop_buf=0.25, stop_max=2.8, min_risk_atr=0.25,
    tp1_r=1.5, tp2_r=3.0, be_off=0.05, session=(7, 21), no_friday_pm=True, vol_min=0.0,
)


def ls_confluence_zones(ind, i, atr, band, min_lv):
    """Raggruppa i livelli LS_LEVEL_KEYS entro band*ATR. -> [(lo, hi, n, center), ...]."""
    lv = []
    for k in LS_LEVEL_KEYS:
        a = ind.get(k)
        v = a[i] if (a is not None and i < len(a)) else None
        if v is not None and v == v:
            lv.append(float(v))
    lv.sort()
    if not lv:
        return []
    out = []
    cur = [lv[0]]
    bw = band * atr
    for x in lv[1:]:
        if x - cur[-1] <= bw:
            cur.append(x)
        else:
            if len(cur) >= min_lv:
                out.append((cur[0], cur[-1], len(cur), sum(cur) / len(cur)))
            cur = [x]
    if len(cur) >= min_lv:
        out.append((cur[0], cur[-1], len(cur), sum(cur) / len(cur)))
    return out


def ls_clean_trend(ind, i, atr, P):
    """'up' / 'down' / None -- trend pulito = EMA200 in pendenza + prezzo dal lato giusto."""
    e_a = ind.get('ema200')
    if e_a is None or i < P['slope_bars']:
        return None
    e = e_a[i]; ep = e_a[i - P['slope_bars']]
    c = ind['C'][i]
    if e is None or ep is None or not atr:
        return None
    slope = (e - ep) / atr
    if slope >= P['slope_min'] and c > e:
        return 'up'
    if slope <= -P['slope_min'] and c < e:
        return 'down'
    return None


def ls_scan(ind, i, state, dt=None, vol_ratio=None, P=None):
    """State machine di INGRESSO. `state` = dict mutabile con chiave 'pending'.
    Ritorna un entry_spec (segnale sulla barra i, esecuzione al next-bar-open) o None.
    NON gestisce la posizione (vedi ls_manage_step).
      entry_spec = {'dir', 'sl', 'tp1', 'tp2', 'risk', 'zone': (lo,hi,n,center)}
    """
    P = P or LS_PARAMS
    C = ind['C']; H = ind['H']; L = ind['L']; O = ind['O']
    atr = ind['atr'][i] if (ind.get('atr') and ind['atr'][i]) else None
    if not atr or atr <= 0 or i < 300:
        return None

    up_s = ind.get('tlb_up_s'); dn_s = ind.get('tlb_dn_s')
    tlu = ind.get('tlb_upper'); tld = ind.get('tlb_lower')

    trend = ls_clean_trend(ind, i, atr, P)
    if trend == 'up' and up_s and up_s[i] and tlu and tlu[i] is not None:
        state['pending'] = {'dir': 'buy', 'L': float(tlu[i]), 'start': i, 'exp': i + P['retest_max']}
    elif trend == 'down' and dn_s and dn_s[i] and tld and tld[i] is not None:
        state['pending'] = {'dir': 'sell', 'L': float(tld[i]), 'start': i, 'exp': i + P['retest_max']}

    pend = state.get('pending')
    if not pend or not (pend['start'] + P['retest_min'] <= i <= pend['exp']):
        if pend and i > pend['exp']:
            state['pending'] = None
        return None

    if dt is not None:
        s0, s1 = P['session']
        if not (s0 <= dt.hour < s1):
            return None
        if P['no_friday_pm'] and dt.weekday() == 4 and dt.hour >= 16:
            return None

    d = pend['dir']; Lb = pend['L']
    zs = ls_confluence_zones(ind, i, atr, P['band'], P['min_lv'])
    tol = P['retest_tol'] * atr
    near = None
    for z in zs:
        if abs(z[3] - Lb) <= tol or (z[0] - tol <= Lb <= z[1] + tol):
            near = z
            break
    if near is None:
        if i >= pend['exp']:
            state['pending'] = None
        return None

    zlo, zhi, zn, zc = near
    c = C[i]; o = O[i]; hi = H[i]; lo = L[i]
    if d == 'buy':
        touched = lo <= zhi + tol
        wick = min(c, o) - lo
        reject = c > o and wick >= P['reject_wick'] * atr and c > zc
    else:
        touched = hi >= zlo - tol
        wick = hi - max(c, o)
        reject = c < o and wick >= P['reject_wick'] * atr and c < zc
    if P['vol_min'] > 0 and vol_ratio is not None:
        if not (vol_ratio == vol_ratio and vol_ratio >= P['vol_min']):
            reject = False
    if not (touched and reject):
        if i >= pend['exp']:
            state['pending'] = None
        return None

    entry_ref = c
    if d == 'buy':
        sl = min(zlo, lo) - P['stop_buf'] * atr
    else:
        sl = max(zhi, hi) + P['stop_buf'] * atr
    risk = abs(entry_ref - sl)
    if risk > P['stop_max'] * atr or risk < P['min_risk_atr'] * atr:
        state['pending'] = None
        return None
    sgn = 1 if d == 'buy' else -1
    fwd = sorted([z for z in zs if (z[3] > entry_ref) == (d == 'buy') and z[3] != zc],
                 key=lambda z: z[3], reverse=(d == 'sell'))
    tp1 = entry_ref + sgn * risk * P['tp1_r']
    tp2 = fwd[1][3] if len(fwd) > 1 else (fwd[0][3] if fwd else entry_ref + sgn * risk * P['tp2_r'])
    if not ((d == 'buy' and entry_ref < tp1 <= tp2) or (d == 'sell' and entry_ref > tp1 >= tp2)):
        tp2 = entry_ref + sgn * risk * P['tp2_r']
    state['pending'] = None
    return {'dir': d, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'risk': risk, 'zone': near}


def ls_manage_step(pos, jh, jl, jc, tlb_low_i, tlb_up_i, atr0, P=None):
    """Un passo di gestione posizione (per barra). Muta `pos` in place.
    pos = {'dir','entry','sl','tp1','tp2','risk','part'(bool),'booked','hh','ll'}
    Ritorna (close_price | None, exit_kind). Priorita: hard SL > TP2.
      - a TP1 (1.5R): chiude 50%, SL -> BE
      - dopo TP1: trailing dietro la trendline LuxAlgo (fallback: giveback 1R)
    """
    P = P or LS_PARAMS
    d = pos['dir']; entry = pos['entry']; R = pos['risk']
    is_buy = d == 'buy'
    be_off = P.get('be_off', 0.05) * atr0
    pos['hh'] = max(pos['hh'], jh); pos['ll'] = min(pos['ll'], jl)

    # TP1 (1.5R) toccato INTRABAR -> chiude 50%, SL a BE (+/- piccolo offset)
    tp1_hit = (jh >= pos['tp1']) if is_buy else (jl <= pos['tp1'])
    if not pos['part'] and tp1_hit:
        m1 = (pos['tp1'] - entry) if is_buy else (entry - pos['tp1'])
        pos['booked'] += 0.5 * m1
        pos['part'] = True
        be = (entry + be_off) if is_buy else (entry - be_off)
        pos['sl'] = max(pos['sl'], be) if is_buy else min(pos['sl'], be)

    if pos['part']:
        tl = tlb_low_i if is_buy else tlb_up_i
        cand = float(tl) if (tl is not None and tl == tl) else ((jc - R) if is_buy else (jc + R))
        pos['sl'] = max(pos['sl'], cand) if is_buy else min(pos['sl'], cand)

    # priorita pessimistica: se la barra tocca sia SL che TP2 -> SL
    hit_sl = (jl <= pos['sl']) if is_buy else (jh >= pos['sl'])
    hit_tp2 = (jh >= pos['tp2']) if is_buy else (jl <= pos['tp2'])
    if hit_sl:
        return pos['sl'], ('sl' if not pos['part'] else 'trail')
    if hit_tp2:
        return pos['tp2'], 'tp2'
    return None, None


def ls_status(ind, i, state, in_position=False, P=None):
    """Stato corrente del setup S31 per la UI (dashboard). Read-only, non muta `state`.
    Ritorna un dict compatto:
      { phase: 'in_position'|'break_pending'|'watching'|'flat',
        trend: 'up'|'down'|None, pending_dir, bars_waiting, bars_left,
        nearest_zone: {center, n_levels, dist_atr} | None, score (0-100) }
    """
    P = P or LS_PARAMS
    C = ind['C']
    atr = ind['atr'][i] if (ind.get('atr') and ind['atr'][i]) else None
    out = {'phase': 'flat', 'trend': None, 'pending_dir': None,
           'bars_waiting': None, 'bars_left': None, 'nearest_zone': None, 'score': 0}
    if not atr or i < 300:
        return out
    trend = ls_clean_trend(ind, i, atr, P)
    out['trend'] = trend
    pend = state.get('pending')
    zs = ls_confluence_zones(ind, i, atr, P['band'], P['min_lv'])
    c = C[i]
    if zs:
        nz = min(zs, key=lambda z: abs(z[3] - c))
        out['nearest_zone'] = {'center': round(nz[3], 2), 'n_levels': nz[2],
                               'dist_atr': round((c - nz[3]) / atr, 2)}
    if in_position:
        out['phase'] = 'in_position'; out['score'] = 100
        return out
    if pend and pend['start'] <= i <= pend['exp']:
        out['phase'] = 'break_pending'
        out['pending_dir'] = pend['dir']
        out['bars_waiting'] = i - pend['start']
        out['bars_left'] = pend['exp'] - i
        # score: più vicino a una zona di confluenza allineata → più alto
        sc = 55
        if out['nearest_zone']:
            d = abs(out['nearest_zone']['dist_atr'])
            sc = int(max(55, min(95, 95 - d * 40)))
        out['score'] = sc
        return out
    if trend:
        out['phase'] = 'watching'; out['score'] = 30
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# S32/S33/S34 — strategie dai layout TradingView XAU_M15 / XAU_M30 / XAU_H1_Volumes
# (2026-09-10). Stessa filosofia di S31: NON meccanizzare gli indicatori ("compra
# quando l'oscillatore incrocia"), ma codificare COME quel toolkit viene tradato.
# Ogni strategia:
#   bias()        -> direzione/regime consentito (filtro istituzionale del layout)
#   scan()        -> entry_spec {dir,sl,tp1,tp2,risk,zone,tag} o None (next-bar-open)
#   manage_step() -> (close_price|None, exit_kind) via _lf_manage_step condiviso
#   status()      -> snapshot per la dashboard (score 0-100, bias, livelli)
# Uscite: SEMPRE TP1 parziale -> BE -> trailing strutturale -> runner a TP2
# (vincolo utente). Backtest: layout_s3x.py. Bot: blocco generico LAYOUT_STRATS.
# ═══════════════════════════════════════════════════════════════════════════════

def _lf_manage_step(pos, jh, jl, jc, trail_buy, trail_sell, atr0, P, hard_exit=False):
    """Un passo di gestione (per barra) condiviso da S32/S33/S34. Muta `pos` in place.
    pos = {'dir','entry','sl','tp1','tp2','risk','part'(bool),'booked','hh','ll'}
      trail_buy  = livello candidato di trailing SL se dir=='buy'  (o None)
      trail_sell = livello candidato di trailing SL se dir=='sell' (o None)
      hard_exit  = True -> chiudi a mercato (jc) ora (es. Supertrend flip / mouth close)
    Ritorna (close_price|None, exit_kind). Priorità: hard SL > hard_exit > TP2.
      - a TP1 (tp1_r·R): chiude tp1_frac, SL -> BE (± be_off·ATR)
      - dopo TP1: trailing dietro trail_* (mai allentato)."""
    d = pos['dir']; entry = pos['entry']; R = pos['risk']
    is_buy = d == 'buy'
    frac = P.get('tp1_frac', 0.5)
    be_off = P.get('be_off', 0.05) * (atr0 or 0.0)
    pos['hh'] = max(pos['hh'], jh); pos['ll'] = min(pos['ll'], jl)

    tp1_hit = (jh >= pos['tp1']) if is_buy else (jl <= pos['tp1'])
    if not pos['part'] and tp1_hit:
        m1 = (pos['tp1'] - entry) if is_buy else (entry - pos['tp1'])
        pos['booked'] += frac * m1
        pos['part'] = True
        be = (entry + be_off) if is_buy else (entry - be_off)
        pos['sl'] = max(pos['sl'], be) if is_buy else min(pos['sl'], be)

    if pos['part']:
        cand = trail_buy if is_buy else trail_sell
        if cand is None or cand != cand:
            cand = (jc - R) if is_buy else (jc + R)      # fallback giveback 1R
        pos['sl'] = max(pos['sl'], cand) if is_buy else min(pos['sl'], cand)

    hit_sl = (jl <= pos['sl']) if is_buy else (jh >= pos['sl'])
    hit_tp2 = (jh >= pos['tp2']) if is_buy else (jl <= pos['tp2'])
    if hit_sl:
        return pos['sl'], ('sl' if not pos['part'] else 'trail')
    if hard_exit:
        return jc, ('signal' if not pos['part'] else 'signal_trail')
    if hit_tp2:
        return pos['tp2'], 'tp2'
    return None, None


def _lf_tps(entry, sl, d, atr, P, fwd_levels=None):
    """TP1 = tp1_r·R fisso; TP2 = prossimo livello strutturale (fwd_levels) o tp2_r·R.
    Garantisce ordine entry<tp1<=tp2 (buy) / entry>tp1>=tp2 (sell)."""
    sgn = 1 if d == 'buy' else -1
    risk = abs(entry - sl)
    tp1 = entry + sgn * risk * P['tp1_r']
    tp2 = entry + sgn * risk * P['tp2_r']
    if fwd_levels:
        cand = [x for x in fwd_levels if x is not None and x == x
                and ((x > tp1) if d == 'buy' else (x < tp1))]
        if cand:
            tp2 = min(cand) if d == 'buy' else max(cand)
    if not ((d == 'buy' and entry < tp1 <= tp2) or (d == 'sell' and entry > tp1 >= tp2)):
        tp2 = entry + sgn * risk * P['tp2_r']
    return tp1, tp2, risk


def _lf_session_ok(dt, P):
    if dt is None:
        return True
    s0, s1 = P.get('session', (0, 24))
    if not (s0 <= dt.hour < s1):
        return False
    if P.get('no_friday_pm', True) and dt.weekday() == 4 and dt.hour >= 16:
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# S32_ORDERFLOW_SCALP — layout XAU_M15 (M5/M15)
#   BB(20,2) · ICT Institutional Order Flow (fadi) · EMA 20/50/100/200 · Order
#   Block Finder · OBV.
#   Come si trada DAVVERO l'order-flow ICT (non "compra in un OB"): si aspetta una
#   LIQUIDITY SWEEP — il prezzo caccia gli stop sotto/sopra un estremo di swing
#   (mecca oltre il minimo/massimo delle ultime K barre) e RIENTRA (close dal lato
#   giusto). Con il ribbon EMA a favore (o almeno EMA200) e OBV che conferma
#   l'assorbimento, si entra sul rientro. Stop oltre lo sweep. TP1 = BB media /
#   swing (parziale) -> BE -> trailing dietro EMA20 -> runner.
#   Ricerca: layout_s3x.py. Solo London+NY.
# ─────────────────────────────────────────────────────────────────────────────
S32_PARAMS = dict(
    sweep_lb=12,                                     # estremo di swing = min/max ultime K barre (esclusa i)
    sweep_pen=0.08,                                  # penetrazione minima oltre l'estremo (·ATR)
    reclaim_max=1.5,                                  # rientro: close entro reclaim_max·ATR dall'estremo, dal lato giusto
    require_ribbon=False,                            # True: pretende stack EMA completo; False: solo EMA200
    ribbon_slope_bars=8,
    obv_confirm=True, obv_slope_bars=3,
    stop_buf=0.25, stop_max=2.6, min_risk_atr=0.20,
    tp1_r=1.3, tp2_r=2.8, tp1_frac=0.5, be_off=0.05,
    session=(7, 21), no_friday_pm=True, cooldown_bars=4,
)


def _s32_ribbon(ind, i, P):
    """'up'/'down'/None — bias del ribbon EMA. Se require_ribbon: stack 20>50>100>200
    completo; altrimenti solo prezzo vs EMA200 + EMA200 in pendenza."""
    e20 = _get(ind, 'e20'); e50 = _get(ind, 'e50'); e100 = _get(ind, 'e100')
    e200 = _get(ind, 'e200', 'e233', 'ema200')
    if not e200 or i < P['ribbon_slope_bars'] or e200[i] is None:
        return None
    px = ind['C'][i]
    e2p = e200[i - P['ribbon_slope_bars']]
    slope_up = e2p is not None and e200[i] > e2p
    if P.get('require_ribbon'):
        if not all((e20, e50, e100)) or None in (e20[i], e50[i], e100[i]):
            return None
        if e20[i] > e50[i] > e100[i] > e200[i] and px > e20[i]:
            return 'up'
        if e20[i] < e50[i] < e100[i] < e200[i] and px < e20[i]:
            return 'down'
        return None
    if px > e200[i] and slope_up:
        return 'up'
    if px < e200[i] and not slope_up:
        return 'down'
    return None


def _s32_obv_ok(ind, i, d, P):
    if not P.get('obv_confirm', True):
        return True
    ov = _get(ind, 'obv')
    lb = P['obv_slope_bars']
    if not ov or i < lb or ov[i] is None or ov[i - lb] is None:
        return True
    return (ov[i] > ov[i - lb]) if d == 'buy' else (ov[i] < ov[i - lb])


def s32_bias(ind, i, P=None):
    return _s32_ribbon(ind, i, P or S32_PARAMS)


def s32_scan(ind, i, state, dt=None, P=None):
    P = P or S32_PARAMS
    C = ind['C']; H = ind['H']; L = ind['L']; O = ind['O']
    atr = ind['atr'][i] if (ind.get('atr') and ind['atr'][i]) else None
    if not atr or atr <= 0 or i < 260:
        return None
    if not _lf_session_ok(dt, P):
        return None
    d = _s32_ribbon(ind, i, P)
    if d is None:
        return None
    lb = P['sweep_lb']
    prior_lo = min(L[i - lb:i]); prior_hi = max(H[i - lb:i])
    c = C[i]; o = O[i]; hi = H[i]; lo = L[i]
    if d == 'up':
        swept = lo < prior_lo - P['sweep_pen'] * atr
        reclaimed = c > prior_lo and c > o and (c - prior_lo) <= P['reclaim_max'] * atr
        if not (swept and reclaimed):
            return None
        dd = 'buy'; sl = lo - P['stop_buf'] * atr
    else:
        swept = hi > prior_hi + P['sweep_pen'] * atr
        reclaimed = c < prior_hi and c < o and (prior_hi - c) <= P['reclaim_max'] * atr
        if not (swept and reclaimed):
            return None
        dd = 'sell'; sl = hi + P['stop_buf'] * atr
    if not _s32_obv_ok(ind, i, dd, P):
        return None
    risk = abs(c - sl)
    if risk > P['stop_max'] * atr or risk < P['min_risk_atr'] * atr:
        return None
    bb_mid = _get(ind, 'bb_mid'); bb_up = _get(ind, 'bb_up'); bb_lo = _get(ind, 'bb_lo', 'bb_dn')
    fwd = []
    if bb_mid and bb_mid[i] is not None:
        fwd.append(bb_mid[i])
    fwd.append(prior_hi if dd == 'buy' else prior_lo)
    if dd == 'buy' and bb_up and bb_up[i] is not None:
        fwd.append(bb_up[i])
    if dd == 'sell' and bb_lo and bb_lo[i] is not None:
        fwd.append(bb_lo[i])
    tp1, tp2, risk = _lf_tps(c, sl, dd, atr, P, fwd_levels=fwd)
    return {'dir': dd, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'risk': risk,
            'zone': 'sweep', 'tag': 'S32_ORDERFLOW_SCALP'}


def s32_manage_step(pos, jh, jl, jc, e20_i, atr0, P=None):
    P = P or S32_PARAMS
    tb = ts = None
    if e20_i is not None and e20_i == e20_i:
        tb = e20_i - 0.10 * (atr0 or 0.0)
        ts = e20_i + 0.10 * (atr0 or 0.0)
    return _lf_manage_step(pos, jh, jl, jc, tb, ts, atr0, P)


def s32_status(ind, i, state, in_position=False, P=None):
    P = P or S32_PARAMS
    out = {'phase': 'flat', 'bias': None, 'zone': None, 'score': 0, 'note': ''}
    atr = ind['atr'][i] if (ind.get('atr') and ind['atr'][i]) else None
    if not atr or i < 260:
        return out
    d = _s32_ribbon(ind, i, P)
    out['bias'] = {'up': 'buy', 'down': 'sell'}.get(d)
    if in_position:
        out['phase'] = 'in_position'; out['score'] = 100
        return out
    if d is None:
        out['note'] = 'bias EMA non definito'
        return out
    C = ind['C']; H = ind['H']; L = ind['L']
    lb = P['sweep_lb']
    prior_lo = min(L[i - lb:i]); prior_hi = max(H[i - lb:i])
    if d == 'up':
        dist = (C[i] - prior_lo) / atr
        near = dist <= 1.2
        swept = L[i] < prior_lo
    else:
        dist = (prior_hi - C[i]) / atr
        near = dist <= 1.2
        swept = H[i] > prior_hi
    if swept:
        out['phase'] = 'sweep'; out['score'] = 78
        out['note'] = f'liquidity sweep {"lows" if d == "up" else "highs"} · attesa rientro'
    elif near:
        out['phase'] = 'armed'; out['score'] = 55
        out['note'] = f'prezzo vicino al livello di liquidità ({dist:.1f} ATR)'
    else:
        out['phase'] = 'watching'; out['score'] = 30
        out['note'] = f'bias {out["bias"]} · lontano dai livelli di liquidità'
    return out


# ─────────────────────────────────────────────────────────────────────────────
# S33_TREND_MOMENTUM — layout XAU_M30 (M30)
#   Supertrend(10,3) · Williams Alligator(13/8/5) · OBV MACD · Ultimate RSI · Momentum.
#   Come si trada: si opera SOLO col Supertrend; si entra quando l'Alligator si
#   "sveglia" (lips separata da teeth/jaw nel verso, prezzo oltre le 3 linee) e il
#   trio momentum conferma (>=2 di: OBV-MACD dir, Ultimate RSI vs 50, Momentum
#   segno); ingresso su pullback alla lips. Stop = Supertrend (o teeth). Runner:
#   TP1 1.5R parziale -> BE -> trailing dietro Supertrend -> exit su flip
#   Supertrend o chiusura bocca Alligator (lips ricrossa teeth).
# ─────────────────────────────────────────────────────────────────────────────
S33_PARAMS = dict(
    mouth_min=0.28,                                 # separazione lips/teeth >= k·ATR (bocca aperta)
    pullback_atr=1.2,                               # |close - lips| <= k·ATR (entry vicino alla lips)
    mom_needed=3,                                   # quante conferme del trio momentum (OBV-MACD / uRSI / Momentum)
    adx_min=26,                                     # trend-momentum: solo in TREND (ADX >= k). None per disattivare
    ursi_mid=50.0,
    stop_mode='supertrend', stop_buf=0.20, stop_max=3.2, min_risk_atr=0.30,
    tp1_r=1.5, tp2_r=3.5, tp1_frac=0.5, be_off=0.05,
    session=(7, 21), no_friday_pm=True, cooldown_bars=3,
)


def _s33_dir(ind, i):
    """Supertrend: engine 'st' -> 1=bearish(prezzo sotto), -1=bullish(prezzo sopra)."""
    st = _get(ind, 'st')
    if not st or st[i] is None:
        return None
    return 'buy' if st[i] == -1 else 'sell'


def _s33_mouth(ind, i, d, P):
    jaw = _get(ind, 'jaw'); teeth = _get(ind, 'teeth'); lips = _get(ind, 'lips')
    atr = ind['atr'][i] if (ind.get('atr') and ind['atr'][i]) else None
    if not all((jaw, teeth, lips)) or None in (jaw[i], teeth[i], lips[i]) or not atr:
        return False
    sep = P['mouth_min'] * atr
    if d == 'buy':
        return lips[i] - teeth[i] >= sep and teeth[i] - jaw[i] >= 0 and ind['C'][i] > lips[i]
    return teeth[i] - lips[i] >= sep and jaw[i] - teeth[i] >= 0 and ind['C'][i] < lips[i]


def _s33_mom_count(ind, i, d):
    n = 0
    oc = _get(ind, 'obv_oc', 'obv_macd_oc')
    if oc and oc[i] is not None:
        n += 1 if ((oc[i] == 1) if d == 'buy' else (oc[i] == -1)) else 0
    ursi = _get(ind, 'ursi'); usig = _get(ind, 'ursi_sig')
    if ursi and ursi[i] is not None:
        up = ursi[i] > 50.0 and (usig[i] is None or ursi[i] >= usig[i])
        n += 1 if (up if d == 'buy' else (not up)) else 0
    mom = _get(ind, 'lmom', 'mom')
    if mom and mom[i] is not None:
        n += 1 if ((mom[i] > 0) if d == 'buy' else (mom[i] < 0)) else 0
    return n


def s33_bias(ind, i, P=None):
    d = _s33_dir(ind, i)
    if d and _s33_mouth(ind, i, d, P or S33_PARAMS):
        return 'up' if d == 'buy' else 'down'
    return None


def s33_scan(ind, i, state, dt=None, P=None):
    P = P or S33_PARAMS
    C = ind['C']; H = ind['H']; L = ind['L']
    atr = ind['atr'][i] if (ind.get('atr') and ind['atr'][i]) else None
    if not atr or atr <= 0 or i < 260:
        return None
    if not _lf_session_ok(dt, P):
        return None
    d = _s33_dir(ind, i)
    if d is None or not _s33_mouth(ind, i, d, P):
        return None
    if P.get('adx_min'):
        ax = _get(ind, 'adx')
        if not ax or ax[i] is None or ax[i] < P['adx_min']:
            return None
    if _s33_mom_count(ind, i, d) < P['mom_needed']:
        return None
    lips = _get(ind, 'lips'); teeth = _get(ind, 'teeth')
    if not lips or lips[i] is None:
        return None
    if abs(C[i] - lips[i]) > P['pullback_atr'] * atr:      # entra solo vicino alla lips
        return None
    st = _get(ind, 'st_level') or _get(ind, 'st')          # engine espone solo dir; usa teeth/swing
    # stop strutturale: teeth (o swing recente) + buffer
    if d == 'buy':
        sl = min(teeth[i] if teeth[i] is not None else L[i], min(L[max(0, i - 4):i + 1])) - P['stop_buf'] * atr
    else:
        sl = max(teeth[i] if teeth[i] is not None else H[i], max(H[max(0, i - 4):i + 1])) + P['stop_buf'] * atr
    risk = abs(C[i] - sl)
    if risk > P['stop_max'] * atr or risk < P['min_risk_atr'] * atr:
        return None
    tp1, tp2, risk = _lf_tps(C[i], sl, d, atr, P)
    return {'dir': d, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'risk': risk,
            'zone': 'alligator', 'tag': 'S33_TREND_MOMENTUM'}


def s33_manage_step(pos, jh, jl, jc, ind_i, atr0, P=None):
    """ind_i = dict con st(dir), jaw/teeth/lips alla barra corrente (per trailing + hard exit)."""
    P = P or S33_PARAMS
    d = pos['dir']
    teeth = ind_i.get('teeth'); lips = ind_i.get('lips'); st = ind_i.get('st')
    tb = ts = None
    ref = teeth if teeth is not None else lips
    if ref is not None and ref == ref:
        tb = ref - 0.15 * (atr0 or 0.0)
        ts = ref + 0.15 * (atr0 or 0.0)
    # hard exit: Supertrend flip contro la posizione, o bocca che si chiude (lips ricrossa teeth)
    hard = False
    if st is not None:
        hard = (st == 1) if d == 'buy' else (st == -1)
    if not hard and teeth is not None and lips is not None:
        hard = (lips < teeth) if d == 'buy' else (lips > teeth)
    return _lf_manage_step(pos, jh, jl, jc, tb, ts, atr0, P, hard_exit=hard)


def s33_status(ind, i, state, in_position=False, P=None):
    P = P or S33_PARAMS
    out = {'phase': 'flat', 'bias': None, 'zone': None, 'score': 0, 'note': ''}
    atr = ind['atr'][i] if (ind.get('atr') and ind['atr'][i]) else None
    if not atr or i < 260:
        return out
    d = _s33_dir(ind, i)
    out['bias'] = d
    if in_position:
        out['phase'] = 'in_position'; out['score'] = 100
        return out
    if d is None:
        return out
    ax = _get(ind, 'adx')
    axv = ax[i] if (ax and ax[i] is not None) else None
    mouth = _s33_mouth(ind, i, d, P)
    mc = _s33_mom_count(ind, i, d)
    if P.get('adx_min') and axv is not None and axv < P['adx_min']:
        out['phase'] = 'wrong_regime'; out['score'] = 15
        out['note'] = (f'Supertrend {d} · ADX {axv:.0f} < {P["adx_min"]} (serve TREND) · '
                       f'bocca {"aperta" if mouth else "chiusa"} · momentum {mc}/3')
        return out
    if mouth and mc >= P['mom_needed']:
        lips = _get(ind, 'lips')
        near = lips and lips[i] is not None and abs(ind['C'][i] - lips[i]) <= P['pullback_atr'] * atr
        out['phase'] = 'armed' if near else 'trend_on'
        out['score'] = 85 if near else 65
        out['note'] = f'Supertrend {d} · bocca aperta · momentum {mc}/3' + ('' if near else ' · attesa pullback lips')
    elif mouth:
        out['phase'] = 'watching'; out['score'] = 45
        out['note'] = f'bocca aperta ma momentum {mc}/3'
    else:
        out['phase'] = 'watching'; out['score'] = 25
        out['note'] = f'Supertrend {d} · Alligator addormentato'
    return out


# ─────────────────────────────────────────────────────────────────────────────
# S34_VOLUME_AUCTION — layout XAU_H1_Volumes (H1)
#   Volume Footprint · Visible Range VP · Session VP · Cumulative Delta Volume ·
#   Normalized Volume.
#   Come si trada (auction market theory): il prezzo si estende al bordo della
#   value area (VAH/VAL del profilo rolling o di sessione), mostra RIFIUTO (mecca
#   + chiusura rientrata in VA), il CVD DIVERGE / gira e il volume normalizzato è
#   ELEVATO (rvol >= k). Si fa fade verso il POC. TP1 = POC (parziale) -> BE ->
#   trailing dietro swing -> runner al bordo opposto della VA. Solo London+NY.
# ─────────────────────────────────────────────────────────────────────────────
S34_PARAMS = dict(
    edge_tol=0.35,                                  # |close - VA edge| <= k·ATR per "al bordo"
    reject_wick=0.22, rvol_min=1.6,                 # rifiuto su volume normalizzato ELEVATO (spike)
    cvd_div_bars=6,                                 # finestra per la divergenza CVD
    use_session_profile=True,                       # True: session VP developing; False: rolling VRVP
    min_va_width_atr=1.2,                           # VA troppo stretta -> niente edge
    adx_max=22,                                     # auction mean-reversion: solo in RANGE (ADX <= k). None per disattivare
    stop_buf=0.25, stop_max=2.8, min_risk_atr=0.30,
    tp1_r=1.4, tp2_r=3.0, tp1_frac=0.5, be_off=0.05,
    session=(7, 21), no_friday_pm=True, cooldown_bars=3,
)


def _s34_profile(ind, i, P):
    """-> (poc, vah, val) del profilo scelto. Se il profilo di sessione IN CORSO non
    è pronto (inizio sessione / fuori sessione), fallback all'ultima sessione completa
    (psvp) e poi al rolling VRVP."""
    def at(k):
        a = _get(ind, k)
        return a[i] if (a is not None and i < len(a)) else None
    if P['use_session_profile']:
        poc, vah, val = at('svp_poc'), at('svp_vah'), at('svp_val')
        if None in (poc, vah, val):
            poc, vah, val = at('psvp_poc'), at('psvp_vah'), at('psvp_val')
    else:
        poc, vah, val = at('vp_poc'), at('vp_vah'), at('vp_val')
    if None in (poc, vah, val):
        poc, vah, val = at('vp_poc'), at('vp_vah'), at('vp_val')
    return poc, vah, val


def _s34_cvd_div(ind, i, d, P):
    """Divergenza CVD sulla finestra: buy -> prezzo fa un minimo <= min recente ma CVD no
    (assorbimento); sell -> speculare sui massimi. Fallback: segno di cvd_ema contro il move."""
    cvd = _get(ind, 'cvd'); ce = _get(ind, 'cvd_ema')
    lb = P['cvd_div_bars']
    C = ind['C']
    if not cvd or i < lb or cvd[i] is None:
        return False
    if d == 'buy':
        px_low = min(C[i - lb:i + 1]); made_low = C[i] <= px_low + 1e-9
        cvd_low = min(x for x in cvd[i - lb:i + 1] if x is not None)
        absorb = made_low and cvd[i] > cvd_low
        turn = ce and ce[i] is not None and ce[i] > 0
        return bool(absorb or turn)
    else:
        px_hi = max(C[i - lb:i + 1]); made_hi = C[i] >= px_hi - 1e-9
        cvd_hi = max(x for x in cvd[i - lb:i + 1] if x is not None)
        absorb = made_hi and cvd[i] < cvd_hi
        turn = ce and ce[i] is not None and ce[i] < 0
        return bool(absorb or turn)


def s34_bias(ind, i, P=None):
    P = P or S34_PARAMS
    poc, vah, val = _s34_profile(ind, i, P)
    c = ind['C'][i]
    if None in (poc, vah, val):
        return None
    if c >= vah:
        return 'down'          # sopra la VA -> bias fade short verso POC
    if c <= val:
        return 'up'            # sotto la VA -> bias fade long verso POC
    return None


def s34_scan(ind, i, state, dt=None, P=None):
    P = P or S34_PARAMS
    C = ind['C']; H = ind['H']; L = ind['L']; O = ind['O']
    atr = ind['atr'][i] if (ind.get('atr') and ind['atr'][i]) else None
    if not atr or atr <= 0 or i < 320:
        return None
    if not _lf_session_ok(dt, P):
        return None
    poc, vah, val = _s34_profile(ind, i, P)
    if None in (poc, vah, val) or (vah - val) < P['min_va_width_atr'] * atr:
        return None
    if P.get('adx_max'):
        ax = _get(ind, 'adx')
        if not ax or ax[i] is None or ax[i] > P['adx_max']:
            return None
    rvol = _get(ind, 'rvol')
    if not rvol or rvol[i] is None or rvol[i] < P['rvol_min']:
        return None
    c = C[i]; o = O[i]; hi = H[i]; lo = L[i]
    tol = P['edge_tol'] * atr
    # long fade a VAL, short fade a VAH
    if lo <= val + tol and c > val:
        d = 'buy'; edge = val; wick = min(c, o) - lo
        reject = c > o and wick >= P['reject_wick'] * atr
    elif hi >= vah - tol and c < vah:
        d = 'sell'; edge = vah; wick = hi - max(c, o)
        reject = c < o and wick >= P['reject_wick'] * atr
    else:
        return None
    if not reject or not _s34_cvd_div(ind, i, d, P):
        return None
    if d == 'buy':
        sl = min(lo, edge) - P['stop_buf'] * atr
    else:
        sl = max(hi, edge) + P['stop_buf'] * atr
    risk = abs(c - sl)
    if risk > P['stop_max'] * atr or risk < P['min_risk_atr'] * atr:
        return None
    far = vah if d == 'buy' else val
    tp1, tp2, risk = _lf_tps(c, sl, d, atr, P, fwd_levels=[poc, far])
    return {'dir': d, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'risk': risk,
            'zone': ('VAL' if d == 'buy' else 'VAH'), 'tag': 'S34_VOLUME_AUCTION'}


def s34_manage_step(pos, jh, jl, jc, swing_low, swing_high, atr0, P=None):
    P = P or S34_PARAMS
    tb = (swing_low - 0.15 * (atr0 or 0.0)) if swing_low is not None else None
    ts = (swing_high + 0.15 * (atr0 or 0.0)) if swing_high is not None else None
    return _lf_manage_step(pos, jh, jl, jc, tb, ts, atr0, P)


def s34_status(ind, i, state, in_position=False, P=None):
    P = P or S34_PARAMS
    out = {'phase': 'flat', 'bias': None, 'zone': None, 'score': 0, 'note': ''}
    atr = ind['atr'][i] if (ind.get('atr') and ind['atr'][i]) else None
    if not atr or i < 320:
        return out
    poc, vah, val = _s34_profile(ind, i, P)
    if in_position:
        out['phase'] = 'in_position'; out['score'] = 100
        return out
    if None in (poc, vah, val):
        out['note'] = 'profilo volume non pronto'
        return out
    ax = _get(ind, 'adx')
    axv = ax[i] if (ax and ax[i] is not None) else None
    if P.get('adx_max') and axv is not None and axv > P['adx_max']:
        out['phase'] = 'wrong_regime'; out['score'] = 15
        out['note'] = f'ADX {axv:.0f} > {P["adx_max"]} (auction MR solo in RANGE)'
        return out
    c = ind['C'][i]; tol = P['edge_tol'] * atr
    rvol = _get(ind, 'rvol'); rv = rvol[i] if (rvol and rvol[i] is not None) else 0.0
    if c <= val + tol:
        d = 'buy'; out['bias'] = 'buy'; out['zone'] = 'VAL'
    elif c >= vah - tol:
        d = 'sell'; out['bias'] = 'sell'; out['zone'] = 'VAH'
    else:
        out['phase'] = 'inside_va'; out['score'] = 20
        out['note'] = f'prezzo dentro la VA (POC {poc:.1f})'
        return out
    div = _s34_cvd_div(ind, i, d, P)
    vol_ok = rv >= P['rvol_min']
    if div and vol_ok:
        out['phase'] = 'armed'; out['score'] = 85
        out['note'] = f'{out["zone"]} · rifiuto + CVD div + rvol {rv:.2f}'
    else:
        out['phase'] = 'at_edge'; out['score'] = 45
        out['note'] = f'{out["zone"]} · manca ' + (' '.join(x for x, ok in (('CVD-div', div), ('rvol', vol_ok)) if not ok))
    return out
