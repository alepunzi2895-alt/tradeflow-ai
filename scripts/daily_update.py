#!/usr/bin/env python3
"""
TradeFlow AI — Daily Update (da eseguire ogni mattina prima dell'apertura mercati)

1. Fetch dati freschi MT5 per tutti i TF (M5, M15, M30, H1, H4, D1)
2. Backtest su dati H1 aggiornati (tutte le strategie via strategy-engine-v2.py)
3. Backtest M30 con risk management (strategy-engine-v2.py --rm)
4. Update Performance Tracker da storico MT5 reale

USAGE:
    python -X utf8 scripts/daily_update.py

PREREQUISITI:
    MT5 deve essere aperto prima di eseguire questo script.

SCHEDULING (Windows Task Scheduler):
    Azione: python -X utf8 C:\\tradeflow-ai\\scripts\\daily_update.py
    Trigger: ogni giorno alle 06:00
"""

import subprocess, sys, os, datetime, logging, time

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_DIR = os.path.join(BASE_DIR, 'scripts')
DATA_DIR   = os.path.join(BASE_DIR, 'data')
LOG_DIR    = BASE_DIR
LOG_FILE   = os.path.join(LOG_DIR, 'daily_update.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger('daily-update')

PYTHON = sys.executable


def run(label, args, timeout=300):
    """Esegue un sottoprocesso, logga output e ritorna True se OK."""
    log.info(f"▶ {label}")
    start = time.time()
    try:
        result = subprocess.run(
            args,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
        )
        elapsed = time.time() - start
        if result.returncode == 0:
            last_lines = result.stdout.strip().splitlines()[-5:]
            for line in last_lines:
                if line.strip():
                    log.info(f"   {line}")
            log.info(f"✅ {label} — OK ({elapsed:.0f}s)")
            return True
        else:
            log.error(f"❌ {label} — exit {result.returncode}")
            for line in (result.stderr or result.stdout or '').splitlines()[-10:]:
                log.error(f"   {line}")
            return False
    except subprocess.TimeoutExpired:
        log.error(f"⏱ {label} — timeout dopo {timeout}s")
        return False
    except Exception as e:
        log.error(f"❌ {label} — eccezione: {e}")
        return False


def main():
    today = datetime.date.today().isoformat()
    log.info('=' * 60)
    log.info(f'TradeFlow AI — Daily Update — {today}')
    log.info('=' * 60)

    results = {}

    # ── 1. Fetch dati MT5 per tutti i TF ──────────────────────────────────────
    log.info('\n── FASE 1: Fetch dati MT5 ──')
    for tf in ['M5', 'M15', 'M30', 'H1', 'H4', 'D1']:
        days = 730 if tf in ('H1', 'H4', 'D1') else 365
        ok = run(
            f'Fetch {tf} ({days}gg)',
            [PYTHON, '-X', 'utf8', os.path.join(SCRIPT_DIR, 'fetch_mt5_history.py'),
             '--tf', tf, '--days', str(days)],
            timeout=120,
        )
        results[f'fetch_{tf}'] = ok
        if not ok:
            log.warning(f'Fetch {tf} fallito — continuo con dati precedenti')

    # ── 2. Backtest H1 (tutte le strategie) ───────────────────────────────────
    log.info('\n── FASE 2: Backtest H1 ──')
    h1_file = os.path.join(DATA_DIR, 'xauusd_h1_mt5.json')
    if os.path.exists(h1_file):
        results['backtest_h1'] = run(
            'Backtest H1 (strategy-engine-v2)',
            [PYTHON, '-X', 'utf8', os.path.join(SCRIPT_DIR, 'strategy-engine-v2.py'),
             '--file', h1_file],
            timeout=300,
        )
    else:
        log.warning('File H1 non trovato — skip backtest H1')
        results['backtest_h1'] = False

    # ── 3. Backtest M30 con Risk Management ───────────────────────────────────
    log.info('\n── FASE 3: Backtest M30 + RM ──')
    m30_file = os.path.join(DATA_DIR, 'xauusd_m30_mt5.json')
    if os.path.exists(m30_file):
        results['backtest_m30'] = run(
            'Backtest M30 --rm',
            [PYTHON, '-X', 'utf8', os.path.join(SCRIPT_DIR, 'strategy-engine-v2.py'),
             '--file', m30_file, '--rm'],
            timeout=300,
        )
    else:
        log.warning('File M30 non trovato — skip backtest M30')
        results['backtest_m30'] = False

    # ── 4. Backtest H4 ───────────────────────────────────────────────────────────
    log.info('\n── FASE 4: Backtest H4 ──')
    h4_file = os.path.join(DATA_DIR, 'xauusd_h4_mt5.json')
    if os.path.exists(h4_file):
        results['backtest_h4'] = run(
            'Backtest H4',
            [PYTHON, '-X', 'utf8', os.path.join(SCRIPT_DIR, 'strategy-engine-v2.py'),
             '--file', h4_file],
            timeout=300,
        )
    else:
        log.warning('File H4 non trovato — skip backtest H4')
        results['backtest_h4'] = False

    # ── 5. Performance Tracker: aggiorna da storico MT5 + applica overrides ──
    log.info('\n── FASE 5: Performance Tracker ──')
    try:
        sys.path.insert(0, SCRIPT_DIR)
        import MetaTrader5 as mt5
        from performance_tracker import get_performance_tracker

        if not mt5.initialize():
            log.warning(f'MT5 non disponibile: {mt5.last_error()} — skip Performance Tracker')
            results['perf_tracker'] = False
        else:
            tracker = get_performance_tracker()
            new_trades = tracker.update_from_mt5(mt5, days_back=90)
            changes    = tracker.auto_apply_adjustments()
            log.info(f'Performance Tracker: +{new_trades} trade, {len(changes)} aggiustamenti')
            log.info(tracker.get_performance_report())
            mt5.shutdown()
            results['perf_tracker'] = True
    except ImportError as e:
        log.warning(f'Import error Performance Tracker: {e}')
        results['perf_tracker'] = False
    except Exception as e:
        log.error(f'Performance Tracker error: {e}')
        results['perf_tracker'] = False

    # ── Riepilogo ─────────────────────────────────────────────────────────────
    log.info('\n── RIEPILOGO ──')
    ok_count  = sum(1 for v in results.values() if v)
    all_count = len(results)
    for k, v in results.items():
        log.info(f"  {'✅' if v else '❌'} {k}")
    log.info(f'\n{ok_count}/{all_count} task completati — {today}')
    log.info('=' * 60)


if __name__ == '__main__':
    main()
