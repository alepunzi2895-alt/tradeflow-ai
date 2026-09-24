#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ricerca 2026-09-24 — S00_MFKK V3: ingressi a regole esplicite (richiesta utente).

Regole utente:
  - ADX >= 25
  - DI+ e DI- si allontanano: spread >= DI_MIN e in crescita vs 2 barre prima
    (direzione = lato DI dominante)
  - MACD: incrocio linea/segnale nella direzione del trade nelle ultime 2 barre,
    OPPURE istogramma ancora contrario ma in contrazione da 2 barre ("sta per girare")
  - CCI (stocastico del CCI, 0-100, come S00) con soglie 40/60 invece di 35/65.
    Due letture, entrambe testate:
      PULL = pullback: BUY se CCI <= 40 in una delle ultime 3 barre, SELL se >= 60
      MOM  = momentum: BUY se CCI >= 60, SELL se CCI <= 40

Invariati rispetto a S00 live: orari (BUY 7-22, SELL 7-20), TP 3.5×ATR / SL 1.5×ATR,
motore run_one (costi, entry next-open, walk-forward, holdout). Nessuna modifica a
signals.py finché una variante non passa is_promotable().

USO: python -X utf8 scripts/research_s00_v3_entries.py
"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import opt_harness as OH
import signals as SIG
import research_trials as RT
from strategy_selector import detect_regime_extended


def make_v3(cci_mode, di_min=10):
    def fn(ind, i, hour=None, tf=None):
        if i < 100:
            return None
        a, dp, dm = ind['adx'][i], ind['dip'][i], ind['dim'][i]
        dp2, dm2 = ind['dip'][i - 2], ind['dim'][i - 2]
        if None in (a, dp, dm, dp2, dm2) or a < 25:
            return None
        d = 'buy' if dp > dm else 'sell'
        if hour is not None and not (7 <= hour < (22 if d == 'buy' else 20)):
            return None
        spread, spread_prev = abs(dp - dm), abs(dp2 - dm2)
        if spread < di_min or spread <= spread_prev or (dp2 > dm2) != (dp > dm):
            return None

        m, s, h = ind['macd'], ind['macd_sig'], ind['macd_hist']
        if None in (m[i], s[i], h[i], m[i - 2], s[i - 2], h[i - 1], h[i - 2]):
            return None
        sgn = 1 if d == 'buy' else -1
        crossed = any((m[k - 1] - s[k - 1]) * sgn <= 0 < (m[k] - s[k]) * sgn for k in (i - 1, i))
        about_to_flip = h[i] * sgn < 0 and abs(h[i]) < abs(h[i - 1]) < abs(h[i - 2])
        if not (crossed or about_to_flip):
            return None

        cci = [x if x is not None else 50.0 for x in ind['cci'][i - 2:i + 1]]
        if cci_mode == 'PULL':
            ok = min(cci) <= 40 if d == 'buy' else max(cci) >= 60
        else:
            ok = cci[-1] >= 60 if d == 'buy' else cci[-1] <= 40
        return d if ok else None
    return fn


def trend_down_stats(ev, tf):
    _, ind = OH._data_for(tf)
    td = [t for t in ev['trades'] if detect_regime_extended(ind, t['entry_idx'])['type'] == 'TREND_DOWN']
    return OH.SE2.stats(td)


def main():
    variants = {
        'PULL_di10': make_v3('PULL', 10),
        'MOM_di10':  make_v3('MOM', 10),
        'PULL_di15': make_v3('PULL', 15),
        'MOM_di15':  make_v3('MOM', 15),
    }
    tfs = ('H1', 'M30')
    num_trials = RT.record_trials(len(variants) * len(tfs), asset='XAU', strategy_id='S00_MFKK',
                                  note='S00 V3 regole utente ADX25/DI widening/MACD cross-preflip/CCI 40-60 (2026-09-24)')
    print(f"Trial cumulativi (per DSR): {num_trials}")

    for tf in tfs:
        base = OH.evaluate('S00_MFKK', SIG.signal_mfkk_score, tf=tf)
        OH.print_eval(f"BASE S00 attuale @ {tf}", base, num_trials)
        print(f"  TREND_DOWN: {OH.fmt(trend_down_stats(base, tf))}")
        pbo_set = {'BASE': base['trades']}
        for name, fn in variants.items():
            ev = OH.evaluate('S00_MFKK', fn, tf=tf)
            OH.print_eval(f"V3 {name} @ {tf}", ev, num_trials)
            print(f"  TREND_DOWN: {OH.fmt(trend_down_stats(ev, tf))}")
            ok, checks = OH.is_promotable(ev, base, num_trials)
            print(f"  promuovibile vs BASE: {ok}  {checks}")
            pbo_set[name] = ev['trades']
        try:
            pbo = OH.pbo_check(pbo_set)
            print(f"\nPBO @ {tf} ({len(pbo_set)} varianti): {pbo.pbo:.2f}")
        except Exception as e:
            print(f"\nPBO @ {tf}: n/d ({e})")


if __name__ == '__main__':
    main()
