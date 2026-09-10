#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Market Structure (SMC): swing HH/HL/LH/LL + BOS / CHoCH  (2026-09-10)
════════════════════════════════════════════════════════════════════════════════════
Gap G1 di `directives/10_trading_education.md` (priorità ALTA — il corso ECABS ci dedica
2 moduli interi, tutti su XAU). Rilevamento CAUSALE (nessun lookahead):

  swing fractal a `wing` barre/lato → noto solo `wing` barre dopo il pivot.
  TREND     : sequenza di swing — up = HH+HL, down = LL+LH, altrimenti range.
  BOS  (Break of Structure)  = CONTINUAZIONE: close oltre l'ultimo swing NEL VERSO del trend.
  CHoCH (Change of Character) = 1° segnale di INVERSIONE: close oltre l'ultimo swing OPPOSTO
                               (in uptrend: sotto l'ultimo Higher-Low; in downtrend: sopra
                               l'ultimo Lower-High).

Uso previsto:
  • feature di regime ("TREND_UP confermato da BOS" vs "TREND_UP ma CHoCH recente → cautela")
  • gate/confidence per S31/S32/S33/S34 (vedi layout_confidence.py)

`structure_arrays(candles, wing=2)` → dict di array lunghi n:
  ms_trend      -1 down / 0 range / +1 up   (stato struttura alla barra i, causale)
  ms_bos        +1 / -1 / 0   (BOS confermato ALLA barra i, nel verso)
  ms_choch      +1 / -1 / 0   (CHoCH confermato ALLA barra i, verso della nuova ipotesi)
  ms_bars_since_bos / ms_bars_since_choch   (int, 9999 se mai)
  ms_last_hh / ms_last_hl / ms_last_lh / ms_last_ll   (prezzo, nan se n/d)
"""
import numpy as np

try:
    from telegram_key_levels import swing_points as _swing_points
except Exception:  # pragma: no cover
    def _swing_points(H, L, wing=2):
        n = len(H)
        last_sh = np.full(n, np.nan); last_sl = np.full(n, np.nan)
        vsh = vsl = np.nan
        for i in range(n):
            k = i - wing
            if k >= wing:
                if H[k] == max(H[k - wing:k + wing + 1]):
                    vsh = H[k]
                if L[k] == min(L[k - wing:k + wing + 1]):
                    vsl = L[k]
            last_sh[i] = vsh; last_sl[i] = vsl
        return last_sh, last_sl


def _confirmed_swings(H, L, wing):
    """Lista cronologica di (idx_conferma, prezzo, kind) con kind in {'H','L'} — l'idx è
    quando lo swing diventa NOTO (pivot + wing)."""
    n = len(H)
    ev = []
    for k in range(wing, n - wing):
        win_h = H[k - wing:k + wing + 1]; win_l = L[k - wing:k + wing + 1]
        if H[k] == max(win_h):
            ev.append((k + wing, float(H[k]), 'H'))
        if L[k] == min(win_l):
            ev.append((k + wing, float(L[k]), 'L'))
    ev.sort(key=lambda x: x[0])
    return ev


def structure_arrays(candles, wing=2):
    H = np.array([c['h'] for c in candles], float)
    L = np.array([c['l'] for c in candles], float)
    C = np.array([c['c'] for c in candles], float)
    n = len(C)
    out = {k: np.zeros(n) for k in ('ms_trend', 'ms_bos', 'ms_choch')}
    for k in ('ms_last_hh', 'ms_last_hl', 'ms_last_lh', 'ms_last_ll'):
        out[k] = np.full(n, np.nan)
    out['ms_bars_since_bos'] = np.full(n, 9999.0)
    out['ms_bars_since_choch'] = np.full(n, 9999.0)

    ev = _confirmed_swings(H, L, wing)
    ei = 0
    highs = []          # prezzi degli ultimi swing high confermati
    lows = []
    trend = 0
    last_hh = last_hl = last_lh = last_ll = np.nan
    last_bos_i = last_choch_i = -10 ** 9

    for i in range(n):
        # integra gli swing che diventano noti alla barra i
        while ei < len(ev) and ev[ei][0] <= i:
            _, price, kind = ev[ei]
            ei += 1
            if kind == 'H':
                prev = highs[-1] if highs else np.nan
                highs.append(price)
                if not np.isnan(prev):
                    if price > prev:
                        last_hh = price
                    else:
                        last_lh = price
            else:
                prev = lows[-1] if lows else np.nan
                lows.append(price)
                if not np.isnan(prev):
                    if price < prev:
                        last_ll = price
                    else:
                        last_hl = price
            # aggiorna il trend dalla sequenza recente
            if len(highs) >= 2 and len(lows) >= 2:
                hh = highs[-1] > highs[-2]
                hl = lows[-1] > lows[-2]
                lh = highs[-1] < highs[-2]
                ll = lows[-1] < lows[-2]
                if hh and hl:
                    trend = 1
                elif lh and ll:
                    trend = -1
                # altrimenti mantiene (transizione)

        # BOS / CHoCH sulla barra i (close-based)
        ref_sh = highs[-1] if highs else np.nan
        ref_sl = lows[-1] if lows else np.nan
        # ultimo higher-low / lower-high di riferimento per il CHoCH
        if trend == 1 and len(lows) >= 1 and not np.isnan(ref_sh):
            if C[i] > ref_sh and (i - last_bos_i) > wing:
                out['ms_bos'][i] = 1; last_bos_i = i
            hl_ref = lows[-1]
            if C[i] < hl_ref and (i - last_choch_i) > wing:
                out['ms_choch'][i] = -1; last_choch_i = i; trend = 0
        elif trend == -1 and len(highs) >= 1 and not np.isnan(ref_sl):
            if C[i] < ref_sl and (i - last_bos_i) > wing:
                out['ms_bos'][i] = -1; last_bos_i = i
            lh_ref = highs[-1]
            if C[i] > lh_ref and (i - last_choch_i) > wing:
                out['ms_choch'][i] = 1; last_choch_i = i; trend = 0

        out['ms_trend'][i] = trend
        out['ms_last_hh'][i] = last_hh
        out['ms_last_hl'][i] = last_hl
        out['ms_last_lh'][i] = last_lh
        out['ms_last_ll'][i] = last_ll
        if last_bos_i > -10 ** 8:
            out['ms_bars_since_bos'][i] = i - last_bos_i
        if last_choch_i > -10 ** 8:
            out['ms_bars_since_choch'][i] = i - last_choch_i
    return {k: v for k, v in out.items()}


if __name__ == '__main__':
    import sys, importlib.util
    spec = importlib.util.spec_from_file_location('se2', 'strategy-engine-v2.py')
    sv = sys.argv; sys.argv = ['x']
    se2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(se2); sys.argv = sv
    candles, _ = se2.load_from_file('../data/xauusd_h1_mt5.json')
    ms = structure_arrays(candles, wing=3)
    i = len(candles) - 2
    print('ultima barra:', {k: (round(float(v[i]), 1) if not np.isnan(v[i]) else None) for k, v in ms.items()})
    print('n BOS:', int((ms['ms_bos'] != 0).sum()), ' n CHoCH:', int((ms['ms_choch'] != 0).sum()),
          ' su', len(candles), 'barre')
    # sanity: distribuzione trend
    import collections
    print('trend dist:', collections.Counter(ms['ms_trend'].tolist()))
