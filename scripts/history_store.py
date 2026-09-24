#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Storici MT5 on-demand per qualunque strumento del registro (2026-09-24)

Funzioni condivise (nessun effetto all'import, a differenza di fetch_mt5_history.py):
  - registro strumenti da public/instruments.json (stessa fonte di UI e API)
  - risoluzione del simbolo broker (campo 'mt5' del registro)
  - download candele MT5 (copy_rates_range, fallback copy_rates_from_pos)
  - salvataggio in data/history/{id}_{tf}.json, stesso formato {candles:[{t,o,h,l,c,v}]}
    usato dal backtester (strategy-engine-v2.load_from_file / opt_harness)
  - indice dei dataset (data/history/index.json) pubblicato in dashboard dal worker

data/history/ è gitignored: file runtime scritti sulla VPS, mai in conflitto con git pull.
Usato da scripts/backtest_worker.py (job 'history' lanciati dal Laboratorio).
"""
import datetime
import json
import math
import os
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
REGISTRY_PATH = os.path.join(ROOT, 'public', 'instruments.json')
HISTORY_DIR = os.path.join(ROOT, 'data', 'history')
INDEX_PATH = os.path.join(HISTORY_DIR, 'index.json')

TF_MAP = {   # nome → (attributo MetaTrader5, minuti per barra)
    'M1': ('TIMEFRAME_M1', 1), 'M5': ('TIMEFRAME_M5', 5), 'M15': ('TIMEFRAME_M15', 15),
    'M30': ('TIMEFRAME_M30', 30), 'H1': ('TIMEFRAME_H1', 60), 'H4': ('TIMEFRAME_H4', 240),
    'D1': ('TIMEFRAME_D1', 1440),
}
MAX_DAYS = 3650
MT5_MAX_BARS = 99_999        # limite pratico di copy_rates_from_pos


def load_registry():
    with open(REGISTRY_PATH, encoding='utf-8') as f:
        return {i['id']: i for i in json.load(f)['instruments']}


def dataset_path(instrument_id, tf):
    return os.path.join(HISTORY_DIR, f"{instrument_id.lower()}_{tf.lower()}.json")


def resolve_symbol(mt5, inst):
    """Primo simbolo del broker visibile/attivabile tra i candidati 'mt5' del registro."""
    for sym in inst.get('mt5', []):
        info = mt5.symbol_info(sym)
        if info is None:
            continue
        if not info.visible:
            mt5.symbol_select(sym, True)
            info = mt5.symbol_info(sym)
        if info and info.visible:
            return sym
    return None


def rates_to_candles(rates, cutoff, point=None):
    """Numpy structured array MT5 → lista dict {t,o,h,l,c,v[,s]}, scartando barre prima di cutoff.
    Con point: 's' = spread della barra in prezzo (colonna 'spread' MT5 × point), usato dal
    composer (strategy_spec.py) per i costi reali per barra."""
    out = []
    for r in rates:
        if float(r['time']) < cutoff:
            continue
        c = float(r['close'])
        if math.isnan(c) or c <= 0:
            continue
        try:
            v = float(r['tick_volume']) or float(r['real_volume'])
        except Exception:
            v = 0.0
        row = {'t': int(r['time']), 'o': float(r['open']), 'h': float(r['high']),
               'l': float(r['low']), 'c': c, 'v': v}
        if point:
            row['s'] = round(float(r['spread']) * point, 10)
        out.append(row)
    return out


def fetch_candles(mt5, symbol, tf, days, point=None):
    tf_attr = getattr(mt5, TF_MAP[tf][0]); tf_min = TF_MAP[tf][1]
    date_to = datetime.datetime.now(datetime.timezone.utc)
    date_from = date_to - datetime.timedelta(days=days + 5)       # buffer weekend/festivi
    cutoff = (date_to - datetime.timedelta(days=days)).timestamp()
    rates = mt5.copy_rates_range(symbol, tf_attr, date_from, date_to)
    if rates is None or len(rates) == 0:
        # TF brevi: il terminale può non avere la storia pre-caricata → per numero di barre
        max_bars = min(int(days * (5 / 7) * (24 * 60) / tf_min * 1.2), MT5_MAX_BARS)
        rates = mt5.copy_rates_from_pos(symbol, tf_attr, 0, max_bars)
    if rates is None or len(rates) == 0:
        return []
    return rates_to_candles(rates, cutoff, point)


MAX_GAP_DAYS = 4.0          # weekend + festività restano sotto; oltre = buco nei dati


def quality(candles, days):
    """Copertura reale: giorni coperti e buco più lungo. Il primo controllo (solo prima/ultima
    barra) si faceva ingannare da risposte MT5 parziali: USDJPY M5 dava set-dic 2024 + oggi,
    con 21 mesi mancanti in mezzo, e risultava 'completo'."""
    if len(candles) < 2:
        return {'span_days': 0.0, 'max_gap_days': None, 'complete': False}
    t = [c['t'] for c in candles]
    gap = max(t[i] - t[i - 1] for i in range(1, len(t))) / 86400
    span = (t[-1] - t[0]) / 86400
    return {'span_days': round(span, 1), 'max_gap_days': round(gap, 1),
            'complete': span >= days * 0.9 and gap <= MAX_GAP_DAYS}


def load_index():
    try:
        with open(INDEX_PATH, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'datasets': {}}


def _save_index(idx):
    os.makedirs(HISTORY_DIR, exist_ok=True)
    tmp = INDEX_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(idx, f, indent=1)
    os.replace(tmp, INDEX_PATH)


def download(mt5, instrument_id, tf, days, registry=None):
    """Scarica e salva uno storico. Ritorna il riepilogo (anche in caso di errore: 'error')."""
    registry = registry or load_registry()
    inst = registry.get(str(instrument_id).upper())
    tf = str(tf).upper()
    if not inst:
        return {'error': f'Strumento non nel registro: {instrument_id}'}
    if tf not in TF_MAP:
        return {'error': f'Timeframe non supportato: {tf}'}
    days = max(1, min(int(days), MAX_DAYS))
    symbol = resolve_symbol(mt5, inst)
    if not symbol:
        return {'error': f"Nessun simbolo del broker trovato per {inst['id']} (candidati: {', '.join(inst.get('mt5', []))})"}
    # Simbolo appena attivato: il terminale scarica lo storico in modo asincrono e le prime
    # risposte coprono solo poche ore (verificato: EURUSD H1 → 21 barre al primo tentativo).
    candles = []
    for attempt in range(6):
        candles = fetch_candles(mt5, symbol, tf, days, mt5.symbol_info(symbol).point)
        if quality(candles, days)['complete']:
            break
        time.sleep(2 + attempt)
    if not candles:
        return {'error': f'MT5 non ha restituito candele {symbol} {tf}: apri il grafico nel terminale per pre-caricare la storia'}
    q = quality(candles, days)
    if q['max_gap_days'] is not None and q['max_gap_days'] > MAX_GAP_DAYS:
        # Buco nei dati: tieni solo il tratto continuo più recente (un backtest su dati con
        # mesi mancanti darebbe risultati falsi), e dillo nel riepilogo.
        t = [c['t'] for c in candles]
        cut = max(i for i in range(1, len(t)) if (t[i] - t[i - 1]) / 86400 > MAX_GAP_DAYS)
        candles = candles[cut:]
        q = quality(candles, days)
    os.makedirs(HISTORY_DIR, exist_ok=True)
    fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    path = dataset_path(inst['id'], tf)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'candles': candles, 'fetched_at': fetched_at, 'source': 'MT5', 'symbol': symbol,
                   'instrument': inst['id'], 'timeframe': tf, 'days': days}, f)
    iso = lambda t: datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')
    summary = {'instrument': inst['id'], 'label': inst['label'], 'tf': tf, 'symbol': symbol,
               'bars': len(candles), 'from': iso(candles[0]['t']), 'to': iso(candles[-1]['t']),
               'days_requested': days, 'fetched_at': fetched_at,
               'file': os.path.relpath(path, ROOT).replace('\\', '/'),
               'span_days': q['span_days'], 'max_gap_days': q['max_gap_days'],
               # Periodo coperto più corto del richiesto: limite barre del terminale (Max bars in
               # chart, ~100k: M5 su 2 anni non ci sta) o storia del broker non disponibile.
               'truncated': not q['complete'],
               'note': None if q['complete'] else
                   f"Coperti {q['span_days']} giorni su {days}: limite barre del terminale MT5 o storia del broker più corta"}
    idx = load_index()
    idx['datasets'][f"{inst['id']}_{tf}"] = summary
    idx['updated_at'] = fetched_at
    _save_index(idx)
    return summary
