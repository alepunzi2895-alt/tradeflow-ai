#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Backtest dei segnali Telegram COSÌ COME SONO (2026-09-07)

A differenza di telegram_signal_study.py (reverse-engineering del timing d'entrata), qui
si simula ESATTAMENTE quello che il canale ha dichiarato — entry range, SL, 4 TP a gamba
equa (lot sizing dal file fornito dal provider, vedi ivan_lot_sizing.py) — per rispondere
alla domanda diretta: seguire questi segnali sarebbe stato profittevole?

Assunzioni di modellazione (nessuna verificabile al 100% dal solo testo dei messaggi):
  - Fill: ordini 'now'/'market' riempiti alla close della prima barra >= timestamp segnale;
    ordini 'limit' riempiti al midpoint della entry zone alla prima barra che la tocca
    (finestra max FILL_WAIT_BARS, altrimenti segnale scartato come "non riempito").
  - Dopo la PRIMA gamba TP chiusa in profitto, lo SL delle gambe rimanenti viene spostato
    a breakeven (prezzo di entry) — pratica esplicitamente menzionata nei messaggi di
    gestione del canale ("SETTATE BE"), non garantita per ogni singolo trade storico.
  - Fill pessimistico se una barra tocca sia SL che un TP nella stessa barra (stessa
    convenzione già usata in strategy-engine-v2.py — SL vince).
  - Gambe "TP: open" (runner senza target fisso) escluse dalla simulazione — solo le
    gambe con TP numerico esplicito sono backtestate.
  - Cost model riusato identico da strategy-engine-v2.py (spread/slippage calibrati sui
    dati broker reali di questo progetto, non specifici del broker del canale).

USO:
    python telegram_signal_backtest.py --tf M15 --balance 1000
"""
import argparse
import bisect
import datetime
import json
import os

import ivan_lot_sizing as lots
import opt_harness as oh

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
SE2 = oh.SE2

FILL_WAIT_BARS = 384   # M15: 4 giorni max di attesa riempimento limit
MAX_HOLD_BARS = 2880   # M15: 30 giorni max di detenzione prima di mark-to-market forzato

# Refusi nel canale sorgente (verificati manualmente, es. "SL @ 48328" invece di ~4832 —
# battitura umana, non bug di parsing): SL/TP a distanza irrealistica dall'entry vengono
# scartati. Soglia scelta empiricamente: p99 delle distanze reali è ~88, il cluster di
# refusi confermati parte da ~1000 — 150 lascia margine senza includere gli errori certi.
MAX_SANE_DISTANCE = 150.0


def load_signals():
    with open(os.path.join(DATA, 'telegram_signals.json'), encoding='utf-8') as f:
        return json.load(f)['signals']


def backtest_signal(candles, times, signal, balance_ref, halve):
    is_buy = signal['direction'] == 'buy'
    lo, hi = sorted([signal['entry_lo'], signal['entry_hi']])
    entry_mid = (lo + hi) / 2.0
    sl = signal['sl']
    tps = signal['tps']
    if sl is None or not tps:
        return []

    # Scarta refusi: SL a distanza irrealistica dall'entry (vedi MAX_SANE_DISTANCE)
    if abs(sl - entry_mid) > MAX_SANE_DISTANCE:
        return []
    # Scarta solo le singole gambe TP con refuso, tieni le altre
    tps = [tp for tp in tps if abs(tp - entry_mid) <= MAX_SANE_DISTANCE]
    if not tps:
        return []

    if signal['ts_unix'] < times[0] or signal['ts_unix'] > times[-1]:
        return []  # segnale fuori dal periodo coperto dai dati — non backtestabile
    start_idx = bisect.bisect_left(times, signal['ts_unix'])
    if start_idx >= len(candles):
        return []

    # ── FILL ──
    fill_idx = fill_price = None
    if signal['order_type'] in ('now', 'market'):
        fill_idx = start_idx
        fill_price = candles[start_idx]['c']
    else:
        for i in range(start_idx, min(start_idx + FILL_WAIT_BARS, len(candles))):
            c = candles[i]
            if c['l'] <= hi and c['h'] >= lo:
                fill_idx = i
                fill_price = (lo + hi) / 2.0
                break
    if fill_idx is None:
        return []

    n_legs = len(tps)
    lot_total = lots.base_total_lot(balance_ref) / (2.0 if halve else 1.0)
    lot_leg = lots._round_lot(lot_total / n_legs)

    remaining = list(enumerate(tps))
    current_sl = sl
    be_moved = False
    leg_exits = {}  # leg_idx -> (exit_price, outcome)
    last_close = fill_price
    last_date_ts = candles[fill_idx]['t']

    for i in range(fill_idx + 1, min(fill_idx + 1 + MAX_HOLD_BARS, len(candles))):
        if not remaining:
            break
        c = candles[i]
        H, L = c['h'], c['l']
        last_close = c['c']
        last_date_ts = c['t']
        sl_hit = (L <= current_sl) if is_buy else (H >= current_sl)
        tp_hit_legs = [(idx, tp) for idx, tp in remaining if ((H >= tp) if is_buy else (L <= tp))]

        if sl_hit:
            # fill pessimistico: barra che tocca sia SL che TP -> SL vince per tutte le gambe rimanenti
            for idx, _ in remaining:
                leg_exits[idx] = (current_sl, 'loss')
            remaining = []
            break

        if tp_hit_legs:
            for idx, tp in tp_hit_legs:
                leg_exits[idx] = (tp, 'win')
            remaining = [x for x in remaining if x[0] not in {idx for idx, _ in tp_hit_legs}]
            if not be_moved:
                current_sl = fill_price
                be_moved = True

    # timeout: gambe ancora aperte -> mark-to-market all'ultima close disponibile
    for idx, tp in remaining:
        outcome = 'win' if ((last_close > fill_price) == is_buy) else 'loss'
        leg_exits[idx] = (last_close, outcome)

    trades = []
    date_str = datetime.datetime.fromtimestamp(
        last_date_ts, tz=datetime.timezone.utc).strftime('%Y-%m-%d')
    for idx, (exit_price, outcome) in leg_exits.items():
        price_diff = (exit_price - fill_price) if is_buy else (fill_price - exit_price)
        gross = price_diff * lot_leg * 100.0
        is_stop_exit = (outcome == 'loss')
        cost = SE2.trade_cost(is_stop_exit) * (lot_leg / 0.01)
        net = round(gross - cost, 2)
        trades.append({
            'date': date_str, 'hour': 0, 'pnl': net,
            'outcome': 'win' if net > 0 else 'loss',
        })
    return trades


def run(tf='M15', balance=1000.0, halve=True):
    path = os.path.join(DATA, f'xauusd_{tf.lower()}_mt5.json')
    candles, _ = SE2.load_from_file(path)
    times = [c['t'] for c in candles]

    signals = load_signals()
    all_trades = []
    n_unfilled = 0
    for s in signals:
        trades = backtest_signal(candles, times, s, balance, halve)
        if not trades:
            n_unfilled += 1
        all_trades.extend(trades)

    print(f"\nSegnali totali: {len(signals)} | senza trade (fuori range dati o non riempiti/senza SL-TP): {n_unfilled}")
    print(f"Gambe TP simulate: {len(all_trades)}")
    print(f"Balance riferimento: {balance}€ | lottaggio dimezzato: {halve}")
    print(f"Lotto totale @ {balance}€: {lots.base_total_lot(balance) / (2 if halve else 1):.2f} "
          f"(÷4 gambe = {lots._round_lot(lots.base_total_lot(balance)/(2 if halve else 1)/4):.2f} per gamba tipica)")

    s = SE2.stats(all_trades)
    print(f"\n=== Risultato aggregato (per-gamba, {tf}) ===")
    print(f"  n={s['n']} WR={s['wr']}% PF={s['pf']} pnl={s['pnl']} DD={s['dd']} "
          f"avg/gg={s['avg_day']} mesi+={s['months']}")

    wf = SE2.walk_forward_report(all_trades, folds=4, holdout_frac=0.2)
    if wf:
        SE2.print_walk_forward(f"Ivan signals {tf}", all_trades, folds=4, holdout_frac=0.2)
    return s, all_trades


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--tf', default='M15')
    ap.add_argument('--balance', type=float, default=1000.0)
    ap.add_argument('--no-halve', action='store_true')
    args = ap.parse_args()
    run(args.tf, args.balance, halve=not args.no_halve)
