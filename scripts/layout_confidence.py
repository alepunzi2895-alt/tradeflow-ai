#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Confidence score per i setup dei layout (S31/S32/S33/S34)  (2026-09-10)
════════════════════════════════════════════════════════════════════════════════════════
Punteggio 0-100 per OGNI setup, costruito da fattori INDIPENDENTI dal trigger d'ingresso
(così che il gating aggiunga informazione vera, non ri-selezioni lo stesso combo overfit).
Pesi FISSI dalla teoria (curriculum ECABS / `directives/10_trading_education.md`) — NON
tunati: l'esperimento è "il sistema intelligente rende profittevoli S32/S33/S34?", non
"trova i pesi che le rendono profittevoli".

Fattori (± punti sul base 40):
  strat_quality   ± (score s3?_status − 50)·0.25      qualità confluenza propria del setup
  mtf_bias        +14 / −10   HTF (H4/H1) nel verso (§9 MTF) — per mean-reversion: +8 se HTF range
  structure       +14 / −12   BOS conferma (trend) · CHoCH nel verso (reversal) · penalità se CHoCH contro (§1 SMC)
  oscillator      +10         RSI/StochRSI estremo nel verso alla zona ("ricetta alta prob." §6)
  premium_disc    +8 / −6     long in discount / short in premium vs swing recente (§4 Fib)
  session         +7 / +3     overlap London+NY 13-16 UTC / sessione singola (§7)
  candle          +6          hammer/shooting-star (regola dei terzi) o engulfing nel verso (§6)
  regime_fit      +8          ADX coerente con l'intento (S33 trend ADX≥25 · S34 range ADX≤22)
  news_vol        −16 / −6    spike ATR (proxy news: no dataset storico) — §10

`setup_confidence(...)` → (score, factors_dict). `conf_tier(score)` → dict lot/label.
"""
import numpy as np

# tier di sizing (mirror RM_TIERS ma guidato dal confidence del setup, non da ADX/MACD generici)
CONF_TIERS = [
    {'max': 55, 'lot': 0.0, 'label': 'SKIP'},
    {'max': 65, 'lot': 0.7, 'label': 'LOW'},
    {'max': 75, 'lot': 1.0, 'label': 'NORMAL'},
    {'max': 85, 'lot': 1.3, 'label': 'HIGH'},
    {'max': 101, 'lot': 1.6, 'label': 'MAX'},
]


def conf_tier(score):
    for t in CONF_TIERS:
        if score < t['max']:
            return t
    return CONF_TIERS[-1]


def _hammer(o, h, l, c, d):
    """Regola dei terzi: corpo nel terzo (superiore per hammer / inferiore per star),
    mecca opposta >= 2/3 del range. d='buy' -> hammer, 'sell' -> shooting star."""
    rng = h - l
    if rng <= 0:
        return False
    body_lo = min(o, c); body_hi = max(o, c)
    if d == 'buy':
        lower_wick = body_lo - l
        return (body_lo >= l + rng * 2 / 3) and (lower_wick >= rng * 0.5)
    upper_wick = h - body_hi
    return (body_hi <= h - rng * 2 / 3) and (upper_wick >= rng * 0.5)


def _engulf(po, pc, o, c, d):
    if d == 'buy':
        return c > o and pc < po and c >= po and o <= pc
    return c < o and pc > po and c <= po and o >= pc


def setup_confidence(ind, i, d, strat, ms=None, htf_bias=None, status_score=None,
                     swing_hi=None, swing_lo=None):
    """
    ind        dict indicatori (rsi, srsi_k, atr, atr30, adx, O/H/L/C)
    d          'buy' / 'sell'
    strat      'S31' / 'S32' / 'S33' / 'S34'
    ms         dict da market_structure.structure_arrays (o None)
    htf_bias   array +1/-1/0 del bias HTF sulla barra i (o None)
    status_score  il .score di s3?_status a questa barra (o None -> 55)
    swing_hi/lo   array last swing high/low (per premium/discount) (o None)
    -> (score float 0-100, factors dict)
    """
    reversal = strat in ('S32', 'S34')
    f = {}
    score = 40.0
    C = ind['C']; O = ind['O']; H = ind['H']; L = ind['L']
    atr = ind['atr'][i] if (ind.get('atr') and ind['atr'][i]) else None
    a30 = ind['atr30'][i] if (ind.get('atr30') and i < len(ind['atr30']) and ind['atr30'][i]) else None

    # 1) qualità del setup (confluenza propria)
    ss = 55.0 if status_score is None else float(status_score)
    f['strat_quality'] = round((ss - 50.0) * 0.25, 1)
    score += f['strat_quality']

    # 2) MTF bias (§9)
    hb = None
    if htf_bias is not None and i < len(htf_bias):
        hb = htf_bias[i]
    if hb is not None:
        want = 1 if d == 'buy' else -1
        if reversal:
            f['mtf_bias'] = 8.0 if hb == 0 else (4.0 if hb == want else -4.0)
        else:
            f['mtf_bias'] = 14.0 if hb == want else (-10.0 if hb == -want else 0.0)
        score += f['mtf_bias']

    # 3) struttura SMC (§1)
    if ms is not None:
        tr = ms['ms_trend'][i]
        b_since_bos = ms['ms_bars_since_bos'][i]
        b_since_choch = ms['ms_bars_since_choch'][i]
        choch_dir = 0
        # verso dell'ultimo CHoCH: cerchiamo indietro l'ultimo != 0
        if b_since_choch < 60:
            j = i - int(b_since_choch)
            if 0 <= j < len(ms['ms_choch']):
                choch_dir = ms['ms_choch'][j]
        want = 1 if d == 'buy' else -1
        if reversal:
            v = 0.0
            if choch_dir == want and b_since_choch <= 20:
                v += 12.0
            if tr == 0:
                v += 6.0
            if tr == -want:              # struttura ancora forte contro il fade -> rischio
                v -= 8.0
            f['structure'] = v
        else:
            v = 0.0
            if tr == want:
                v += 8.0
            if b_since_bos <= 12 and ms['ms_bos'][max(0, i - int(b_since_bos))] == want:
                v += 6.0
            if choch_dir == -want and b_since_choch <= 15:
                v -= 12.0
            f['structure'] = v
        score += f['structure']

    # 4) conferma oscillatore alla zona (§6, solo reversal)
    if reversal:
        r = ind['rsi'][i] if (ind.get('rsi') and ind['rsi'][i] is not None) else None
        sk = None
        for k in ('srsi_k', 'stoch_k'):
            a = ind.get(k)
            if a is not None and i < len(a) and a[i] is not None:
                sk = a[i]; break
        osc = 0.0
        if d == 'buy':
            if (r is not None and r < 35) or (sk is not None and sk < 25):
                osc = 10.0
        else:
            if (r is not None and r > 65) or (sk is not None and sk > 75):
                osc = 10.0
        f['oscillator'] = osc
        score += osc

    # 5) premium / discount vs swing recente (§4)
    sh = swing_hi[i] if (swing_hi is not None and i < len(swing_hi)) else None
    sl_ = swing_lo[i] if (swing_lo is not None and i < len(swing_lo)) else None
    if sh is not None and sl_ is not None and sh > sl_ and np.isfinite(sh) and np.isfinite(sl_):
        pos = (C[i] - sl_) / (sh - sl_)
        if d == 'buy':
            f['premium_disc'] = 8.0 if pos < 0.5 else -6.0
        else:
            f['premium_disc'] = 8.0 if pos > 0.5 else -6.0
        score += f['premium_disc']

    # 6) sessione (§7) — hour UTC deve essere passato via ind['_hour'] o dedotto
    hour = ind.get('_hour')
    if hour is not None:
        if 13 <= hour < 16:
            f['session'] = 7.0
        elif 8 <= hour < 21:
            f['session'] = 3.0
        else:
            f['session'] = 0.0
        score += f['session']

    # 7) candela reale nel verso (§6)
    cndl = 0.0
    if _hammer(O[i], H[i], L[i], C[i], d):
        cndl = 6.0
    elif i > 0 and _engulf(O[i - 1], C[i - 1], O[i], C[i], d):
        cndl = 6.0
    f['candle'] = cndl
    score += cndl

    # 8) regime fit
    ax = ind['adx'][i] if (ind.get('adx') and ind['adx'][i] is not None) else None
    if ax is not None:
        if strat == 'S33':
            f['regime_fit'] = 8.0 if ax >= 25 else (-6.0 if ax < 18 else 0.0)
        elif strat == 'S34':
            f['regime_fit'] = 8.0 if ax <= 22 else (-6.0 if ax > 28 else 0.0)
        elif strat == 'S31':
            f['regime_fit'] = 6.0 if ax >= 20 else 0.0
        else:
            f['regime_fit'] = 0.0
        score += f['regime_fit']

    # 9) news / volatilità (proxy: nessun dataset news storico) §10
    if atr and a30:
        rv = atr / a30
        if rv > 2.5:
            f['news_vol'] = -16.0
        elif rv > 1.6:
            f['news_vol'] = -6.0
        else:
            f['news_vol'] = 0.0
        score += f['news_vol']

    score = max(0.0, min(100.0, score))
    return score, f


# ════════════════════════════════════════════════════════════════════════════════
# indicator_readout — stato PER-INDICATORE di ogni layout, per le card "stile MFKK"
# in dashboard. Ogni voce: {value, score (-100 ribassista .. +100 rialzista, o 0..100
# per i non-direzionali), state}. Difensivo: chiave mancante -> riga saltata.
# ════════════════════════════════════════════════════════════════════════════════
def _clamp(x, lo=-100.0, hi=100.0):
    return max(lo, min(hi, x))


def _row(value, score, state):
    return {'value': value, 'score': round(float(score), 0), 'state': state}


def indicator_readout(ind, i, key, ms=None):
    C = ind.get('C'); H = ind.get('H'); L = ind.get('L'); V = ind.get('V')
    atr = ind['atr'][i] if (ind.get('atr') and i < len(ind['atr']) and ind['atr'][i]) else None
    out = {}

    def g(k):
        a = ind.get(k)
        return a[i] if (a is not None and i < len(a) and a[i] is not None) else None

    if key == 'S31':
        up_s, dn_s = ind.get('tlb_up_s'), ind.get('tlb_dn_s')
        tu, td = g('tlb_upper'), g('tlb_lower')
        broke = 0
        for b in range(max(0, i - 6), i + 1):
            if up_s and b < len(up_s) and up_s[b]:
                broke = 1
            if dn_s and b < len(dn_s) and dn_s[b]:
                broke = -1
        sc = broke * 70 if broke else 0
        out['Trendlines w/ Breaks'] = _row(
            ('rotta ↑' if broke > 0 else 'rotta ↓' if broke < 0 else 'nessuna rottura'),
            sc, 'LuxAlgo len 14')
        p = g('dpiv')
        if p is not None and atr:
            d = (C[i] - p) / atr
            out['Pivot Fibonacci'] = _row(f'P {p:.1f} ({d:+.1f} ATR)', _clamp(d * 35),
                                          'sopra P' if d > 0 else 'sotto P')
        lv = []
        for k in ('pdh', 'pdl', 'pwh', 'pwl', 'sess_lon_hi', 'sess_lon_lo', 'sess_ny_hi', 'sess_ny_lo'):
            v = g(k)
            if v is not None:
                lv.append((abs(C[i] - v), v, k))
        if lv and atr:
            lv.sort()
            _, nv, nk = lv[0]
            dd = (C[i] - nv) / atr
            out['Key Levels'] = _row(f'{nk.upper()} {nv:.1f} ({dd:+.1f} ATR)',
                                     _clamp(-dd * 25), 'vicino a un livello' if abs(dd) < 0.5 else 'spazio libero')
        e2 = g('ema200') or g('e200') or g('e233')
        if e2 is not None and atr:
            e2p = None
            for k in ('ema200', 'e200', 'e233'):
                a = ind.get(k)
                if a is not None and i >= 10 and a[i - 10] is not None:
                    e2p = a[i - 10]; break
            slope = ((e2 - e2p) / atr) if e2p is not None else 0.0
            side = 1 if C[i] > e2 else -1
            out['EMA 200'] = _row(f'{e2:.1f} (slope {slope:+.2f})',
                                  _clamp(slope * 45 + side * 25),
                                  'trend su' if slope > 0.1 else 'trend giù' if slope < -0.1 else 'piatta')
        hr = ind.get('_hour')
        if hr is not None:
            sess = ('Overlap Ldn+NY' if 13 <= hr < 16 else 'London' if 8 <= hr < 13
                    else 'New York' if 16 <= hr < 21 else 'Asia/off')
            out['Sessione'] = _row(sess, 60 if 13 <= hr < 16 else 20 if 8 <= hr < 21 else -20,
                                   'liquidità alta' if 13 <= hr < 16 else 'ok' if 8 <= hr < 21 else 'sottile')

    elif key == 'S32':
        bu, bl, bm = g('bb_up'), g('bb_lo') or g('bb_dn'), g('bb_mid')
        if bu and bl and bm and bu > bl:
            pctb = (C[i] - bl) / (bu - bl)
            out['Bollinger Bands'] = _row(f'%B {pctb:.2f}', _clamp((pctb - 0.5) * 160),
                                          'banda alta' if pctb > 0.8 else 'banda bassa' if pctb < 0.2 else 'centro')
        if ms is not None:
            tr = ms['ms_trend'][i]
            bb = ms['ms_bars_since_bos'][i]; bc = ms['ms_bars_since_choch'][i]
            st = ('BOS ' + ('↑' if tr > 0 else '↓')) if bb <= 10 else \
                 ('CHoCH recente' if bc <= 12 else ('trend ↑' if tr > 0 else 'trend ↓' if tr < 0 else 'range'))
            out['ICT Order Flow'] = _row(st, _clamp(tr * 55 + (20 if bb <= 10 else 0) * (1 if tr > 0 else -1)),
                                         'struttura ' + ('rialzista' if tr > 0 else 'ribassista' if tr < 0 else 'neutra'))
        e20, e50, e100, e200 = g('e20'), g('e50'), g('e100'), g('e200') or g('e233')
        if None not in (e20, e50, e100, e200):
            ups = (e20 > e50) + (e50 > e100) + (e100 > e200)
            sc = (ups - 1.5) / 1.5 * 85
            out['EMA 20/50/100/200'] = _row(
                'stack ↑' if ups == 3 else 'stack ↓' if ups == 0 else 'misto', sc,
                'ribbon allineato' if ups in (0, 3) else 'ribbon incrociato')
        ob_b = g('ob_bull'); ob_s = g('ob_bear')
        out['Order Block Finder'] = _row(
            'in Bull OB' if ob_b else 'in Bear OB' if ob_s else 'nessun OB attivo',
            55 if ob_b else -55 if ob_s else 0, 'zona smart-money' if (ob_b or ob_s) else '—')
        ov = ind.get('obv')
        if ov and i >= 5 and ov[i] is not None and ov[i - 5] is not None:
            sl = ov[i] - ov[i - 5]
            rng = max(abs(x) for x in ov[max(0, i - 40):i + 1]) or 1
            out['OBV'] = _row('slope ' + ('↑' if sl > 0 else '↓'),
                              _clamp(sl / rng * 200), 'volume a favore' if abs(sl) > rng * 0.1 else 'piatto')

    elif key == 'S33':
        st = g('st')
        if st is not None:
            out['Supertrend'] = _row('rialzista' if st == -1 else 'ribassista',
                                     -st * 85, 'prezzo sopra la banda' if st == -1 else 'prezzo sotto la banda')
        jaw, teeth, lips = g('jaw'), g('teeth'), g('lips')
        if None not in (jaw, teeth, lips) and atr:
            up = lips > teeth > jaw
            dn = lips < teeth < jaw
            sep = abs(lips - jaw) / atr
            out['Williams Alligator'] = _row(
                f'bocca {"↑" if up else "↓" if dn else "chiusa"} (sep {sep:.1f} ATR)',
                (85 if up else -85 if dn else 0) * min(1.0, sep / 0.6),
                'trend in corso' if (up or dn) and sep > 0.3 else 'addormentato')
        oc = g('obv_oc') or g('obv_macd_oc')
        if oc is not None:
            out['OBV MACD'] = _row('rialzista' if oc == 1 else 'ribassista' if oc == -1 else 'neutro',
                                   oc * 60, 'momentum volume')
        ur, us = g('ursi'), g('ursi_sig')
        if ur is not None:
            cross = 10 if (us is not None and ((ur > us) == (ur > 50))) else 0
            out['Ultimate RSI'] = _row(f'{ur:.1f}' + (f' / sig {us:.1f}' if us is not None else ''),
                                       _clamp((ur - 50) * 1.6 + cross * (1 if ur > 50 else -1)),
                                       'sopra 50' if ur > 50 else 'sotto 50')
        mom = g('lmom') or g('mom')
        if mom is not None and atr:
            out['Momentum'] = _row(f'{mom:+.1f}', _clamp(mom / (1.5 * atr) * 100),
                                   'positivo' if mom > 0 else 'negativo')

    elif key == 'S34':
        cd = g('cvd_delta')
        if cd is not None and V and V[i]:
            out['Volume Footprint (delta)'] = _row(f'{cd:+.0f}', _clamp(cd / (V[i] * 0.5 or 1) * 100),
                                                   'compratori' if cd > 0 else 'venditori')
        for lbl, pfx in (('Visible Range VP', 'vp_'), ('Session VP', 'svp_')):
            poc, vah, val = g(pfx + 'poc'), g(pfx + 'vah'), g(pfx + 'val')
            if pfx == 'svp_' and None in (poc, vah, val):
                poc, vah, val = g('psvp_poc'), g('psvp_vah'), g('psvp_val')
            if None not in (poc, vah, val) and vah > val:
                if C[i] >= vah:
                    stt, sc = 'sopra VAH (esteso ↓)', -55
                elif C[i] <= val:
                    stt, sc = 'sotto VAL (esteso ↑)', 55
                else:
                    p = (C[i] - val) / (vah - val)
                    stt, sc = f'in value area ({p:.0%})', _clamp((0.5 - p) * 60)
                out[lbl] = _row(f'POC {poc:.1f} · VA {val:.0f}-{vah:.0f}', sc, stt)
        cv, ce = g('cvd'), g('cvd_ema')
        if cv is not None:
            out['Cumulative Delta'] = _row(f'{cv / 1000:+.1f}K',
                                           _clamp((ce or 0) / 300 * 100 if ce else (1 if cv > 0 else -1) * 30),
                                           'pressione ' + ('rialzista' if (ce or cv) > 0 else 'ribassista'))
        rv = g('rvol')
        if rv is not None:
            out['Normalized Volume'] = _row(f'{rv:.2f}x', max(0.0, _clamp((rv - 1) * 80, 0, 100)),
                                            'spike' if rv >= 1.6 else 'elevato' if rv >= 1.2 else 'normale' if rv >= 0.7 else 'basso')

    return out
