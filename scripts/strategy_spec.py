#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Composer di strategie: interprete delle specifiche JSON (2026-09-24)

Una strategia composta nel Laboratorio è una SPECIFICA (JSON), non codice:
  {
    "v": 1, "name": "...", "instrument": "XAU", "tf": "H1", "direction": "long"|"short",
    "rules": [{"left":"ema","period":20,"op":"crossUp","right":"ema","value":0,"rightPeriod":50}, ...],
    "session": {"from": 10, "to": 14} | null,          # ora BROKER della candela di segnale
    "exit": {"stop": {"type":"atr","mult":1.5,"period":14} | {"type":"pct","value":1.0}
                     | {"type":"donchian","period":20,"buffer_atr":0.3},
             "take_r": 2.0,
             "partial": {"at_r": 1.0, "fraction": 0.5} | null,   # + stop a pareggio sul resto
             "time_stop_bars": 48 | null},
    "max_trades_per_day": 10
  }
Regole: stesso schema e STESSE FORMULE del motore del browser (public/modules/lab-engine.js,
porting riga per riga) — segnale sulla candela chiusa i-1, ingresso all'apertura della i.
La parità dei segnali JS↔Python è verificata da scripts/test_strategy_spec.py.

Esecuzione realistica: costi dallo spread REALE di ogni barra MT5 (campo 's' degli storici
history_store, pagato all'ingresso; +50% dello spread come slippage sugli stop), fill
pessimistico (stop prima del target nella stessa barra), gap oltre lo stop all'apertura,
una posizione alla volta.

Validazione e criteri di promozione: vedi GATES / evaluate(). Ogni esecuzione è registrata
come trial in data/research_trials.json (serve al DSR: provare 50 varianti e tenere la
migliore NON è una scoperta).
"""
import datetime
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

CATALOG = ['macd', 'macdSignal', 'macdHist', 'adx', 'diPlus', 'diMinus', 'close', 'sma', 'ema', 'rsi', 'atr',
           'roc', 'momentum', 'std', 'bbUpper', 'bbLower', 'stoch', 'williams', 'cci', 'donHigh', 'donLow',
           'volume', 'obv']
OPS = ['gt', 'lt', 'crossUp', 'crossDown']
TFS = ['M5', 'M15', 'M30', 'H1', 'H4', 'D1']
MAX_RULES = 8


# ── Indicatori: porting fedele di LabEngine.indicator (lab-engine.js) ─────────────────
def indicator(data, key, p):
    if key not in CATALOG:
        raise ValueError('Indicatore sconosciuto')
    if not isinstance(p, int) or p < 2 or p > 250:
        raise ValueError('Periodo indicatore: intero da 2 a 250.')
    n = len(data)
    if key.startswith('macd'):
        def ema(values, k):
            out = []; v = values[0]
            for i, x in enumerate(values):
                v = v + 2 / (k + 1) * (x - v) if i else x
                out.append(v)
            return out
        prices = [x['c'] for x in data]
        fast, slow = ema(prices, 12), ema(prices, 26)
        line = [f - s for f, s in zip(fast, slow)]
        signal = ema(line, 9)
        return [None if i < 33 else (x if key == 'macd' else signal[i] if key == 'macdSignal' else x - signal[i])
                for i, x in enumerate(line)]
    if key in ('adx', 'diPlus', 'diMinus'):
        values = [None] * n
        tr_sum = plus = minus = dx_sum = 0.0; adx = None
        for i in range(1, n):
            c, prev = data[i], data[i - 1]
            up, down = c['h'] - prev['h'], prev['l'] - c['l']
            tr = max(c['h'] - c['l'], abs(c['h'] - prev['c']), abs(c['l'] - prev['c']))
            dp = up if (up > down and up > 0) else 0
            dm = down if (down > up and down > 0) else 0
            if i <= p:
                tr_sum += tr; plus += dp; minus += dm
            else:
                tr_sum = tr_sum - tr_sum / p + tr; plus = plus - plus / p + dp; minus = minus - minus / p + dm
            if i < p:
                continue
            dip = 100 * plus / tr_sum if tr_sum else 0
            dim = 100 * minus / tr_sum if tr_sum else 0
            dx = 100 * abs(dip - dim) / (dip + dim) if (dip + dim) else 0
            if i < 2 * p:
                dx_sum += dx
                if i == 2 * p - 1:
                    adx = dx_sum / p
            else:
                adx = (adx * (p - 1) + dx) / p
            values[i] = adx if key == 'adx' else dip if key == 'diPlus' else dim
        return values
    out = [None] * n
    ema = avg_gain = avg_loss = atr = obv = 0.0
    has_volume = True
    for i in range(n):
        c = data[i]; prev = data[i - 1] if i else None
        delta = c['c'] - prev['c'] if prev else 0
        ema = ema + 2 / (p + 1) * (c['c'] - ema) if i else c['c']
        tr = max(c['h'] - c['l'], abs(c['h'] - prev['c']), abs(c['l'] - prev['c'])) if prev else c['h'] - c['l']
        if i < p:
            atr += tr / p
            if i:
                avg_gain += max(delta, 0) / p; avg_loss += max(-delta, 0) / p
        else:
            atr = (atr * (p - 1) + tr) / p
            if i == p:
                avg_gain = avg_gain + max(delta, 0) / p; avg_loss = avg_loss + max(-delta, 0) / p
            else:
                avg_gain = (avg_gain * (p - 1) + max(delta, 0)) / p; avg_loss = (avg_loss * (p - 1) + max(-delta, 0)) / p
        v = c.get('v')
        has_volume = has_volume and v is not None
        if v is not None:
            obv += (1 if delta > 0 else -1 if delta < 0 else 0) * v
        if key == 'close':
            out[i] = c['c']; continue
        if key == 'volume':
            out[i] = v; continue
        if key == 'obv':
            out[i] = obv if has_volume else None; continue
        if i < p - 1:
            continue
        rsi = None if i < p else (50 if avg_gain + avg_loss == 0 else 100 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss))
        fast = {'ema': ema, 'rsi': rsi, 'atr': atr,
                'roc': None if i < p else (c['c'] / data[i - p]['c'] - 1) * 100,
                'momentum': None if i < p else c['c'] - data[i - p]['c']}
        if key in fast:
            out[i] = fast[key]; continue
        if key in ('donHigh', 'donLow'):
            if i < p:
                continue
            prevw = data[i - p:i]
            out[i] = max(x['h'] for x in prevw) if key == 'donHigh' else min(x['l'] for x in prevw)
            continue
        w = data[i - p + 1:i + 1]
        mean = sum(x['c'] for x in w) / p
        sd = math.sqrt(sum((x['c'] - mean) ** 2 for x in w) / p)
        hi = max(x['h'] for x in w); lo = min(x['l'] for x in w)
        tp = [(x['h'] + x['l'] + x['c']) / 3 for x in w]; tm = sum(tp) / p
        md = sum(abs(x - tm) for x in tp) / p
        values = {'sma': mean, 'std': sd, 'bbUpper': mean + 2 * sd, 'bbLower': mean - 2 * sd,
                  'stoch': 50 if hi == lo else 100 * (c['c'] - lo) / (hi - lo),
                  'williams': -50 if hi == lo else -100 * (hi - c['c']) / (hi - lo),
                  'cci': ((c['h'] + c['l'] + c['c']) / 3 - tm) / (.015 * md) if md else 0}
        out[i] = values[key]
    return out


# ── Validazione della specifica (stessi limiti di lib/strategy-spec.js) ────────────────
def validate(spec):
    if not isinstance(spec, dict):
        raise ValueError('Specifica non valida')
    if spec.get('tf') not in TFS:
        raise ValueError('Timeframe non supportato')
    if spec.get('direction') not in ('long', 'short'):
        raise ValueError('Direzione: long o short')
    rules = spec.get('rules')
    if not isinstance(rules, list) or not 1 <= len(rules) <= MAX_RULES:
        raise ValueError(f'Da 1 a {MAX_RULES} regole')
    for r in rules:
        if r.get('left') not in CATALOG or r.get('op') not in OPS:
            raise ValueError('Regola non valida')
        if r.get('right') != 'number' and r.get('right') not in CATALOG:
            raise ValueError('Confronto non valido')
    ex = spec.get('exit') or {}
    st = ex.get('stop') or {}
    if st.get('type') not in ('atr', 'pct', 'donchian'):
        raise ValueError('Tipo di stop non valido')
    if not 0.2 <= float(ex.get('take_r', 0)) <= 20:
        raise ValueError('Target: da 0,2R a 20R')
    return True


def signals(data, rules):
    """Array booleano: la candela chiusa i soddisfa tutte le regole (come matches() del browser)."""
    cache = {}
    def get(key, p):
        k = (key, p)
        if k not in cache:
            cache[k] = indicator(data, key, p)
        return cache[k]
    prepared = []
    for r in rules:
        a = get(r['left'], int(r['period']))
        b = [float(r['value'])] * len(data) if r['right'] == 'number' else get(r['right'], int(r['rightPeriod']))
        prepared.append((r['op'], a, b))
    out = [False] * len(data)
    for i in range(len(data)):
        ok = True
        for op, a, b in prepared:
            x, y = a[i], b[i]
            if x is None or y is None:
                ok = False; break
            if op == 'gt':
                ok = x > y
            elif op == 'lt':
                ok = x < y
            else:
                if i < 1 or a[i - 1] is None or b[i - 1] is None:
                    ok = False
                elif op == 'crossUp':
                    ok = x > y and a[i - 1] <= b[i - 1]
                else:
                    ok = x < y and a[i - 1] >= b[i - 1]
            if not ok:
                break
        out[i] = ok
    return out


# ── Simulazione ──────────────────────────────────────────────────────────────────────
def _hour(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).hour


def simulate(data, spec, cost_mult=1.0, fallback_spread=0.0):
    ex = spec['exit']; st = ex['stop']; sign = 1 if spec['direction'] == 'long' else -1
    sig = signals(data, spec['rules'])
    atr_p = int(st.get('period', 14)) if st['type'] == 'atr' else 14
    atr = indicator(data, 'atr', atr_p)
    don_p = int(st.get('period', 20))
    sess = spec.get('session') or None
    max_day = int(spec.get('max_trades_per_day', 10) or 10)
    partial = ex.get('partial') or None
    tstop = int(ex['time_stop_bars']) if ex.get('time_stop_bars') else None
    trades, per_day = [], {}
    i = 1
    n = len(data)
    while i < n:
        j = i - 1                                              # candela di segnale (chiusa)
        if not sig[j]:
            i += 1; continue
        if sess and not (int(sess['from']) <= _hour(data[j]['t']) < int(sess['to'])):
            i += 1; continue
        day = datetime.datetime.fromtimestamp(data[j]['t'], datetime.timezone.utc).strftime('%Y-%m-%d')
        if per_day.get(day, 0) >= max_day:
            i += 1; continue
        entry = data[i]['o']
        if st['type'] == 'atr':
            if atr[j] is None:
                i += 1; continue
            stop = entry - sign * float(st['mult']) * atr[j]
        elif st['type'] == 'pct':
            stop = entry * (1 - sign * float(st['value']) / 100)
        else:
            if j < don_p or atr[j] is None:
                i += 1; continue
            w = data[j - don_p + 1:j + 1]
            buf = float(st.get('buffer_atr', 0.3)) * atr[j]
            stop = (min(x['l'] for x in w) - buf) if sign == 1 else (max(x['h'] for x in w) + buf)
        risk = (entry - stop) * sign
        if risk <= 0:
            i += 1; continue
        target = entry + sign * float(ex['take_r']) * risk
        t1 = entry + sign * float(partial['at_r']) * risk if partial else None
        frac = float(partial['fraction']) if partial else 0.0
        spread = data[i].get('s', data[j].get('s', fallback_spread)) or fallback_spread
        banked = None; exit_px = None; reason = None; k = i
        cur_stop = stop
        while k < n:
            b = data[k]
            hit_stop = b['l'] <= cur_stop if sign == 1 else b['h'] >= cur_stop
            if hit_stop:
                exit_px = min(b['o'], cur_stop) if sign == 1 else max(b['o'], cur_stop)
                reason = 'stop' if banked is None else 'pareggio'
                break
            if t1 is not None and banked is None and (b['h'] >= t1 if sign == 1 else b['l'] <= t1):
                banked = t1; cur_stop = entry
            if b['h'] >= target if sign == 1 else b['l'] <= target:
                exit_px = target; reason = 'target'; break
            if tstop and k - i + 1 >= tstop:
                exit_px = b['c']; reason = 'tempo'; break
            k += 1
        if exit_px is None:
            k = n - 1; exit_px = data[k]['c']; reason = 'fine dati'
        leg = (exit_px - entry) * sign
        gross = (frac * (banked - entry) * sign + (1 - frac) * leg) if banked is not None else leg
        cost = spread * cost_mult * (1.5 if reason == 'stop' else 1.0)
        pnl = gross - cost
        trades.append({'date': day, 'hour': _hour(data[j]['t']), 'dir': spec['direction'], 'entry': entry,
                       'pnl': pnl, 'r': pnl / risk, 'outcome': 'win' if pnl > 0 else 'loss', 'reason': reason,
                       'entry_idx': i, 'exit_idx': k, 'entry_ts': data[i]['t'], 'exit_ts': data[k]['t']})
        per_day[day] = per_day.get(day, 0) + 1
        i = k + 1                                              # una posizione alla volta
    return trades


# ── Criteri di promozione (fissi, mostrati in UI) ─────────────────────────────────────
GATES = [
    ('sample',   'Campione: almeno 100 trade in totale e 25 negli ultimi mesi'),
    ('pf_full',  'Profit factor su tutto il periodo ≥ 1,20'),
    ('holdout',  'Ultimi mesi mai usati (20%): PF ≥ 1,10 e in utile'),
    ('folds',    'Walk-forward: almeno 3 periodi su 4 con PF ≥ 1'),
    ('costs2',   'Con costi raddoppiati PF ≥ 1,05'),
    ('recovery', 'Guadagno netto ≥ 2 volte il drawdown massimo (in R)'),
    ('dsr',      'Significativo dopo aver contato tutti i tentativi (Deflated Sharpe Ratio)'),
]


def _r_stats(trades):
    eq = peak = dd = 0.0
    for t in trades:
        eq += t['r']; peak = max(peak, eq); dd = max(dd, peak - eq)
    return round(eq, 2), round(dd, 2)


def load_dataset(instrument, tf, mt5=None, days=730, max_age_days=3):
    import history_store as HS
    path = HS.dataset_path(instrument, tf)
    fresh = False
    if os.path.exists(path):
        age = (datetime.datetime.now().timestamp() - os.path.getmtime(path)) / 86400
        try:
            idx = HS.load_index()['datasets'].get(f'{instrument}_{tf}', {})
            # Storico più corto del richiesto (non per limite del terminale) o senza spread per
            # barra (scaricato prima del 2026-09-24) → riscarica: la validazione vuole ~2 anni e costi reali.
            short = (idx.get('span_days') or 0) < days * 0.9 and not idx.get('truncated')
            with open(path, encoding='utf-8') as f:
                tail = json.load(f)['candles'][-5:]
            no_spread = not any('s' in c for c in tail)
        except Exception:
            short = no_spread = True
        fresh = age <= max_age_days and not short and not no_spread
    if not fresh:
        if mt5 is None:
            if not os.path.exists(path):
                raise ValueError(f'Storico {instrument} {tf} assente: scaricalo dal Laboratorio')
        else:
            res = HS.download(mt5, instrument, tf, days)
            if res.get('error'):
                raise ValueError(res['error'])
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    return d['candles'], d


def evaluate(spec, mt5=None, record_trial=True):
    import opt_harness as OH
    import research_trials as RT
    validate(spec)
    candles, meta = load_dataset(spec['instrument'], spec['tf'], mt5)
    has_spread = any('s' in c for c in candles[-50:])
    fallback = 0.0
    if not has_spread:
        try:
            with open(os.path.join(HERE, '..', 'data', 'history', 'profiles.json'), encoding='utf-8') as f:
                fallback = json.load(f)['instruments'][spec['instrument']]['costs']['spread_median'] or 0.0
        except Exception:
            fallback = 0.0
    trades = simulate(candles, spec, 1.0, fallback)
    trades2 = simulate(candles, spec, 2.0, fallback)
    SE2 = OH.SE2
    num_trials = RT.record_trials(1, asset=spec['instrument'], strategy_id='LAB:' + str(spec.get('name', ''))[:40],
                                  note=f"composer {spec['tf']} {spec['direction']} {len(spec['rules'])} regole") if record_trial else RT.total_trials()
    full = SE2.stats(trades)
    wf = SE2.walk_forward_report(trades, folds=4, holdout_frac=0.2) if len(trades) >= 10 else None
    hold = wf['holdout'] if wf else SE2.stats([])
    folds = wf['folds'] if wf else []
    s2 = SE2.stats(trades2)
    net_r, dd_r = _r_stats(trades)
    dsr = OH.dsr_check({'trades': trades}, num_trials) if len(trades) >= 10 else None
    checks = {
        'sample': full['n'] >= 100 and hold['n'] >= 25,
        'pf_full': full['n'] > 0 and full['pf'] >= 1.2,
        'holdout': hold['n'] > 0 and hold['pf'] >= 1.1 and hold['pnl'] > 0,
        'folds': sum(1 for f in folds if f['pf'] >= 1) >= 3,
        'costs2': s2['n'] > 0 and s2['pf'] >= 1.05,
        'recovery': dd_r > 0 and net_r >= 2 * dd_r or (dd_r == 0 and net_r > 0),
        'dsr': bool(dsr is not None and dsr.is_significant),
    }
    core = all(v for k, v in checks.items() if k != 'dsr')
    verdict = 'PROMUOVIBILE' if all(checks.values()) else 'CANDIDATA DEMO' if core else 'BOCCIATA'
    eq, curve = 0.0, []
    step = max(1, len(trades) // 150)
    for idx, t in enumerate(trades):
        eq += t['r']
        if idx % step == 0 or idx == len(trades) - 1:
            curve.append(round(eq, 2))
    months = len({t['date'][:7] for t in trades}) or 1
    return {
        'name': spec.get('name'), 'instrument': spec['instrument'], 'tf': spec['tf'], 'direction': spec['direction'],
        'dataset': {'bars': len(candles), 'from': datetime.datetime.fromtimestamp(candles[0]['t'], datetime.timezone.utc).strftime('%Y-%m-%d'),
                    'to': datetime.datetime.fromtimestamp(candles[-1]['t'], datetime.timezone.utc).strftime('%Y-%m-%d'),
                    'symbol': meta.get('symbol'), 'spread': 'reale per barra' if has_spread else f'mediano {fallback}'},
        'full': full, 'holdout': hold, 'holdout_start': wf['holdout_start'] if wf else None,
        'folds': [{'n': f['n'], 'pf': f['pf']} for f in folds], 'costs2': s2,
        'net_r': net_r, 'max_dd_r': dd_r, 'avg_r': round(net_r / len(trades), 3) if trades else 0,
        'trades_per_month': round(len(trades) / months, 1),
        'dsr': None if dsr is None else {'sr': round(float(dsr.observed_sr), 3), 'p': round(float(dsr.dsr_pvalue), 4),
                                         'significant': bool(dsr.is_significant)},
        'num_trials': num_trials,
        'gates': [{'id': gid, 'label': label, 'ok': bool(checks[gid])} for gid, label in GATES],
        'verdict': verdict, 'equity_r': curve,
        'by_reason': {r: sum(1 for t in trades if t['reason'] == r) for r in ('target', 'stop', 'pareggio', 'tempo', 'fine dati')},
    }


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    spec = json.loads(open(sys.argv[1], encoding='utf-8').read())
    res = evaluate(spec, record_trial='--no-trial' not in sys.argv)
    print(json.dumps({k: res[k] for k in ('verdict', 'full', 'holdout', 'folds', 'costs2', 'net_r', 'max_dd_r', 'gates', 'dsr')}, indent=1, ensure_ascii=False))
