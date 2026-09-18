#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Worker per i backtest on-demand lanciati dalla dashboard (2026-09-17)
═══════════════════════════════════════════════════════════════════════════════
Il bottone "🔄 Lancia backtest" nel tab Strategie mette una richiesta in coda su Turso
(azione backtest_cmd_push). Questo script, in esecuzione separata dal bot live (per non
rallentare i cicli di trading con un backtest che richiede secondi-minuti), fa polling
della coda, esegue portfolio_backtest.evaluate_one() per la strategia richiesta e posta
il risultato (azione backtest_result_push) — la dashboard lo legge via backtest_result_get
e aggiorna la card di quella strategia.

Nessuna logica duplicata: riusa evaluate_one() da portfolio_backtest.py (stessa funzione
usata dal run completo/giornaliero).

USO (lascialo aperto in un terminale, come mt5-bot.py):
    python -X utf8 scripts/backtest_worker.py
    python -X utf8 scripts/backtest_worker.py --interval 10   (polling ogni 10s, default 15)
"""
import argparse
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from portfolio_backtest import evaluate_one
from vercel_push import push

ALL_IDS = ['S00_MFKK', 'S09_MFKK_SCALPING', 'S10_OB_FVG_SCALP', 'S16_GOLDEN_SQUEEZE',
           'S17_CONVERGENCE_SCALP', 'S18_RANGE_REVERSAL', 'S20_FIB_CONFLUENCE',
           'S31_LAYOUT_SMART', 'S30_DOW_DIP']


def handle_command(cmd):
    sid = cmd.get('strategy_id')
    print(f"[backtest_worker] richiesta ricevuta: {sid} (chiesta alle {cmd.get('requested_at')})")
    if sid not in ALL_IDS:
        push('backtest_result_push', {'strategy_id': sid, 'request_id':cmd.get('request_id'), 'lease_token':cmd.get('lease_token'), 'result': {'error': f'strategy_id sconosciuto: {sid}'}})
        print(f"[backtest_worker] ✗ {sid}: id sconosciuto")
        return
    try:
        t0 = time.time()
        result = evaluate_one(sid)
        result['computed_in_s'] = round(time.time() - t0, 1)
        push('backtest_result_push', {'strategy_id': sid, 'request_id':cmd.get('request_id'), 'lease_token':cmd.get('lease_token'), 'result': result}, timeout=30)
        print(f"[backtest_worker] ✓ {sid} completato in {result['computed_in_s']}s — "
              f"full PF {result['full'].get('pf')} holdout PF {result['holdout'].get('pf')}")
    except Exception as e:
        traceback.print_exc()
        try:
            push('backtest_result_push', {'strategy_id': sid, 'request_id':cmd.get('request_id'), 'lease_token':cmd.get('lease_token'), 'result': {'error': str(e)}})
        except Exception:
            pass
        print(f"[backtest_worker] ✗ {sid} fallito: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--interval', type=int, default=15, help='Secondi tra un poll e il successivo')
    args = ap.parse_args()
    print(f"[backtest_worker] avviato — polling ogni {args.interval}s. Ctrl+C per fermare.")
    while True:
        try:
            d = push('backtest_cmd_get', {}, timeout=10)
        except Exception as e:
            print(f"[backtest_worker] poll fallito (rete/Turso down?): {e}")
            time.sleep(args.interval)
            continue
        cmd = (d or {}).get('command')
        if cmd:
            handle_command(cmd)
        time.sleep(args.interval)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n[backtest_worker] fermato.")
