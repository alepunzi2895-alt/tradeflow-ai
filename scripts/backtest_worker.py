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

USO: parte da solo all'avvio di mt5-bot.py (2026-09-24, in una finestra dedicata; disattivabile
con WORKER_AUTOSTART=0 in .env). Si può anche lanciare a mano:
    python -X utf8 scripts/backtest_worker.py
    python -X utf8 scripts/backtest_worker.py --interval 10   (polling ogni 10s, default 15)

Una sola istanza per macchina: il worker occupa la porta locale WORKER_LOCK_PORT (127.0.0.1);
una seconda copia (es. bot riavviato) la trova occupata ed esce subito.

2026-09-24: gestisce anche i job kind='history' (storici MT5 on-demand dal Laboratorio, via
history_store.py) e pubblica ogni ~60s uno heartbeat + l'indice degli storici scaricati
(worker_status_push), così la dashboard sa se il worker è vivo.
"""
import argparse
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import socket
from dotenv import load_dotenv
load_dotenv(os.path.join(HERE, '..', '.env'))   # prima mancava: lanciato da solo non aveva MT5_BOT_SECRET

from portfolio_backtest import evaluate_one
from vercel_push import push

ALL_IDS = ['S00_MFKK', 'S09_MFKK_SCALPING', 'S10_OB_FVG_SCALP', 'S16_GOLDEN_SQUEEZE',
           'S17_CONVERGENCE_SCALP', 'S18_RANGE_REVERSAL', 'S20_FIB_CONFLUENCE',
           'S31_LAYOUT_SMART', 'S30_DOW_DIP']


WORKER_LOCK_PORT = int(os.getenv('WORKER_LOCK_PORT', '47391'))
ERRORS = {}          # ultimi errori per area, pubblicati nell'heartbeat (diagnosi da remoto)


def note_error(area, e):
    import datetime as _dt
    ERRORS[area] = {'at': _dt.datetime.now(_dt.timezone.utc).isoformat(timespec='seconds'),
                    'error': f'{type(e).__name__}: {e}'[:300]}
    print(f"[backtest_worker] ✗ {area}: {ERRORS[area]['error']}")
HEARTBEAT_S = 60
_mt5 = None


def acquire_single_instance():
    """Lucchetto via porta locale: se un altro worker è già attivo, ritorna None."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('127.0.0.1', WORKER_LOCK_PORT))
        s.listen(1)
        return s
    except OSError:
        s.close()
        return None


def mt5_ready():
    """Connessione MT5 lazy (solo quando serve un job di storico). Stesso terminale del bot:
    la libreria MetaTrader5 supporta più processi Python collegati allo stesso terminale."""
    global _mt5
    if _mt5 is None:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            raise RuntimeError(f'MT5 initialize() fallito: {mt5.last_error()} — MT5 è aperto?')
        _mt5 = mt5
    return _mt5


def push_status():
    import history_store
    push('worker_status_push', {'host': socket.gethostname(), 'history': history_store.load_index(),
                                'errors': ERRORS, 'python': sys.version.split()[0]}, timeout=15)


def handle_history(cmd):
    import history_store
    p = cmd.get('params') or {}
    print(f"[backtest_worker] storico richiesto: {p.get('instrument')} {p.get('tf')} {p.get('days')}gg")
    try:
        t0 = time.time()
        result = history_store.download(mt5_ready(), p.get('instrument'), p.get('tf'), p.get('days', 365))
        result['computed_in_s'] = round(time.time() - t0, 1)
    except Exception as e:
        traceback.print_exc()
        result = {'error': str(e)}
    push('backtest_result_push', {'strategy_id': 'HISTORY', 'request_id': cmd.get('request_id'),
                                  'lease_token': cmd.get('lease_token'), 'result': result}, timeout=30)
    if result.get('error'):
        print(f"[backtest_worker] ✗ storico: {result['error']}")
    else:
        print(f"[backtest_worker] ✓ {result['instrument']} {result['tf']}: {result['bars']} barre "
              f"{result['from']} → {result['to']}" + (f" · {result['note']}" if result.get('note') else ''))
        try: push_status()
        except Exception as e: print(f"[backtest_worker] indice non pubblicato: {e}")


PROFILE_MAX_AGE_H = 24


def refresh_profiles(reason):
    """Schede strumento (instrument_profile.py) → dashboard. Ritorna il riepilogo o l'errore."""
    import instrument_profile
    t0 = time.time()
    res = instrument_profile.build_profiles(mt5_ready())
    push('profiles_push', {'profiles': res}, timeout=30)
    print(f"[backtest_worker] ✓ schede strumento aggiornate ({reason}): {len(res['instruments'])} strumenti "
          f"in {time.time() - t0:.0f}s")
    return {'instruments': len(res['instruments']), 'generated_at': res['generated_at'],
            'computed_in_s': round(time.time() - t0, 1)}


def maybe_refresh_profiles():
    import instrument_profile
    age = instrument_profile.cached_age_hours()
    if age is None or age >= PROFILE_MAX_AGE_H:
        try:
            refresh_profiles('giornaliero' if age is not None else 'primo avvio')
            ERRORS.pop('schede', None)
        except Exception as e:
            traceback.print_exc()
            note_error('schede', e)


def handle_profile(cmd):
    try:
        result = refresh_profiles('richiesta dalla dashboard')
    except Exception as e:
        traceback.print_exc(); result = {'error': str(e)}
    push('backtest_result_push', {'strategy_id': 'PROFILE', 'request_id': cmd.get('request_id'),
                                  'lease_token': cmd.get('lease_token'), 'result': result}, timeout=30)


def handle_spec(cmd):
    """Composer: valida una specifica (strategy_spec.evaluate) sui dati MT5 con i criteri di promozione."""
    import strategy_spec
    spec = cmd.get('params') or {}
    print(f"[backtest_worker] composer: '{spec.get('name')}' {spec.get('instrument')} {spec.get('tf')} {spec.get('direction')}")
    try:
        t0 = time.time()
        result = strategy_spec.evaluate(spec, mt5_ready())
        result['computed_in_s'] = round(time.time() - t0, 1)
        print(f"[backtest_worker] ✓ {result['verdict']} · {result['full']['n']} trade · PF {result['full']['pf']} · "
              f"holdout PF {result['holdout']['pf']} · {result['computed_in_s']}s")
    except Exception as e:
        traceback.print_exc(); result = {'error': str(e)}
    push('backtest_result_push', {'strategy_id': 'SPEC', 'request_id': cmd.get('request_id'),
                                  'lease_token': cmd.get('lease_token'), 'result': result}, timeout=30)


def handle_command(cmd):
    if cmd.get('kind') == 'history':
        return handle_history(cmd)
    if cmd.get('kind') == 'spec':
        return handle_spec(cmd)
    if cmd.get('kind') == 'profile':
        return handle_profile(cmd)
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
    lock = acquire_single_instance()
    if lock is None:
        print(f"[backtest_worker] già attivo su questa macchina (porta {WORKER_LOCK_PORT} occupata) — esco.")
        return
    print(f"[backtest_worker] avviato — polling ogni {args.interval}s. Ctrl+C per fermare.")
    last_beat = 0.0
    last_profile_check = 0.0
    while True:
        if time.time() - last_profile_check >= 3600:      # controllo orario, ricalcolo se > 24h
            last_profile_check = time.time()
            maybe_refresh_profiles()
        if time.time() - last_beat >= HEARTBEAT_S:
            try:
                push_status(); last_beat = time.time()
            except Exception as e:
                print(f"[backtest_worker] heartbeat fallito: {e}")
                last_beat = time.time()
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
