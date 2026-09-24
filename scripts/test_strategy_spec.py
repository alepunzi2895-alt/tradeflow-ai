#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parità composer: stesse regole → stessi trade nel motore del browser (lab-engine.js) e in
quello Python (strategy_spec.py), su dati reali. Poi controlli di validazione e criteri.
USO: python -X utf8 scripts/test_strategy_spec.py   (serve data/xauusd_h1_mt5.json + node)"""
import json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import strategy_spec as SS

ROOT = os.path.join(HERE, '..')
data = json.load(open(os.path.join(ROOT, 'data', 'xauusd_h1_mt5.json'), encoding='utf-8'))['candles'][-6000:]
data = [{k: c[k] for k in ('t', 'o', 'h', 'l', 'c', 'v')} for c in data]
CASES = [
    ('long', [{'left': 'ema', 'period': 20, 'op': 'crossUp', 'right': 'ema', 'value': 0, 'rightPeriod': 50}]),
    ('short', [{'left': 'rsi', 'period': 14, 'op': 'gt', 'right': 'number', 'value': 70, 'rightPeriod': 14},
               {'left': 'macd', 'period': 14, 'op': 'crossDown', 'right': 'macdSignal', 'value': 0, 'rightPeriod': 14}]),
    ('long', [{'left': 'adx', 'period': 14, 'op': 'gt', 'right': 'number', 'value': 25, 'rightPeriod': 14},
              {'left': 'diPlus', 'period': 14, 'op': 'gt', 'right': 'diMinus', 'value': 0, 'rightPeriod': 14},
              {'left': 'close', 'period': 14, 'op': 'gt', 'right': 'donHigh', 'value': 0, 'rightPeriod': 20}]),
    ('long', [{'left': 'cci', 'period': 20, 'op': 'crossUp', 'right': 'number', 'value': -100, 'rightPeriod': 14},
              {'left': 'stoch', 'period': 14, 'op': 'lt', 'right': 'number', 'value': 30, 'rightPeriod': 14},
              {'left': 'close', 'period': 14, 'op': 'gt', 'right': 'bbLower', 'value': 0, 'rightPeriod': 20}]),
    ('short', [{'left': 'williams', 'period': 14, 'op': 'gt', 'right': 'number', 'value': -20, 'rightPeriod': 14},
               {'left': 'obv', 'period': 14, 'op': 'lt', 'right': 'number', 'value': 1e12, 'rightPeriod': 14},
               {'left': 'roc', 'period': 10, 'op': 'gt', 'right': 'momentum', 'value': 0, 'rightPeriod': 10}]),
    ('long', [{'left': 'close', 'period': 14, 'op': 'gt', 'right': 'sma', 'value': 0, 'rightPeriod': 50},
              {'left': 'bbUpper', 'period': 20, 'op': 'gt', 'right': 'close', 'value': 0, 'rightPeriod': 14},
              {'left': 'std', 'period': 20, 'op': 'lt', 'right': 'atr', 'value': 0, 'rightPeriod': 14},
              {'left': 'volume', 'period': 14, 'op': 'gt', 'right': 'number', 'value': 0, 'rightPeriod': 14},
              {'left': 'macdHist', 'period': 14, 'op': 'gt', 'right': 'number', 'value': 0, 'rightPeriod': 14}]),
    ('short', [{'left': 'close', 'period': 14, 'op': 'crossDown', 'right': 'donLow', 'value': 0, 'rightPeriod': 10}]),
]
STOP, TAKE = 0.6, 1.2
js = r"""
const fs=require('fs'),vm=require('vm');const ctx={};vm.createContext(ctx);
vm.runInContext(fs.readFileSync('public/modules/lab-engine.js','utf8')+';this.LabEngine=LabEngine;',ctx);
const {data,cases,stop,take}=JSON.parse(fs.readFileSync(0,'utf8'));
const out=cases.map(([direction,rules])=>ctx.LabEngine.run(ctx.LabEngine.normalize(data),{rules,direction,stop,take,cost:0,quantity:1}).trades.map(t=>[t.index,t.exitTime]));
process.stdout.write(JSON.stringify(out));"""
res = subprocess.run(['node', '-e', js], input=json.dumps({'data': data, 'cases': CASES, 'stop': STOP, 'take': TAKE}),
                     capture_output=True, text=True, cwd=ROOT, check=True)
js_trades = json.loads(res.stdout)
for (direction, rules), jt in zip(CASES, js_trades):
    spec = {'tf': 'H1', 'direction': direction, 'rules': rules,
            'exit': {'stop': {'type': 'pct', 'value': STOP}, 'take_r': TAKE / STOP, 'partial': None, 'time_stop_bars': None},
            'max_trades_per_day': 1000}
    SS.validate(spec)
    pt = [[t['entry_idx'], t['exit_ts']] for t in SS.simulate(data, spec)]
    assert len(pt) > 0, f'nessun trade per {rules}'
    assert pt == jt, f"divergenza {direction} {[r['left'] for r in rules]}: python {len(pt)} js {len(jt)} primo diverso {next((a, b) for a, b in zip(pt, jt) if a != b) if any(a != b for a, b in zip(pt, jt)) else 'lunghezza'}"
    print(f"  ✓ {direction:5s} {'+'.join(r['left'] for r in rules):28s} {len(pt)} trade identici")
# Validazione
for bad in [{'tf': 'H2'}, {'tf': 'H1', 'direction': 'up'}, {'tf': 'H1', 'direction': 'long', 'rules': []}]:
    try:
        SS.validate(bad); raise AssertionError('validazione mancata')
    except ValueError:
        pass
# Uscite strutturate: parziale + pareggio non peggiora il win rate; stop ATR usa ATR della candela di segnale
spec = {'tf': 'H1', 'direction': 'long', 'rules': CASES[0][1],
        'exit': {'stop': {'type': 'atr', 'mult': 1.5, 'period': 14}, 'take_r': 2, 'partial': None, 'time_stop_bars': None}}
a = SS.simulate(data, spec, fallback_spread=0.4)
spec['exit']['partial'] = {'at_r': 1, 'fraction': 0.5}
b = SS.simulate(data, spec, fallback_spread=0.4)
wr = lambda tr: sum(t['pnl'] > 0 for t in tr) / len(tr)
assert wr(b) >= wr(a), 'la parziale a 1R + pareggio deve alzare il win rate'
assert all(abs(t['r']) < 25 for t in a + b)
print(f"  ✓ uscite: WR {wr(a):.0%} → {wr(b):.0%} con parziale 1R + pareggio")
print('Composer: parità browser/Python e uscite strutturate — passed')
