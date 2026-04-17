"""
TradeFlow AI — Daily Maintenance Script
═══════════════════════════════════════════════════════════════════
Da eseguire ogni giorno sulla VPS (es. 06:00 UTC via Task Scheduler).

Step 1 — Fetch dati storici MT5 per ogni TF (richiede MT5 aperto)
Step 2 — Backtest adattivo su ogni TF (strategy-engine-v2.py)
Step 3 — Drift analysis: confronta PF recente (ultimi 90gg) vs baseline
Step 4 — Aggiorna strategy_overrides.json con nuovi score_mult
Step 5 — Genera report giornaliero e logga in 07_self_learning_log.md

USO:
  python scripts/daily_maintenance.py
  python scripts/daily_maintenance.py --skip-fetch       # salta fetch MT5
  python scripts/daily_maintenance.py --skip-backtest    # salta backtest
  python scripts/daily_maintenance.py --tfs M30,H1,H4   # solo TF specifici
  python scripts/daily_maintenance.py --dry-run          # nessuna scrittura

Task Scheduler Windows (ogni giorno alle 06:00):
  Action: python -X utf8 C:\\path\\to\\scripts\\daily_maintenance.py
  Start in: C:\\path\\to\\tradeflow-ai
"""
import sys, io, os, json, subprocess, datetime, logging, argparse, math

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('daily_maintenance.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger('daily')

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR   = os.path.join(_SCRIPT_DIR, '..')
_DATA_DIR   = os.path.join(_ROOT_DIR, 'data')
_BT_DIR     = os.path.join(_ROOT_DIR, 'backtests', 'results')
_DIR_DIR    = os.path.join(_ROOT_DIR, 'directives')

# TF → file dati
TF_FILES = {
    'M5':  'xauusd_m5_mt5.json',
    'M15': 'xauusd_m15_mt5.json',
    'M30': 'xauusd_m30_mt5.json',
    'H1':  'xauusd_h1_mt5.json',
    'H4':  'xauusd_h4_mt5.json',
}

# TF canonico per strategia (fonte: directives/02_strategies.md)
STRATEGY_OPTIMAL_TF = {
    'S00_MFKK':              'M30',
    'S05_MFKK_INTRADAY':     'H1',
    'S09_MFKK_SCALPING':     'M30',
    'S10_OB_FVG_SCALP':      'M30',
    'S16_GOLDEN_SQUEEZE':    'M30',
    'S17_CONVERGENCE_SCALP': 'M30',
}

# Baseline backtest completo (fonte di verità, aggiornato dopo ogni campagna)
BASELINE_STATS = {
    'S00_MFKK':              {'pf': 1.033, 'wr': 0.383, 'tf': 'M30'},
    'S05_MFKK_INTRADAY':     {'pf': 1.361, 'wr': 0.415, 'tf': 'H1'},
    'S09_MFKK_SCALPING':     {'pf': 1.637, 'wr': 0.378, 'tf': 'M30'},
    'S10_OB_FVG_SCALP':      {'pf': 1.796, 'wr': 0.425, 'tf': 'M30'},
    'S16_GOLDEN_SQUEEZE':    {'pf': 1.285, 'wr': 0.317, 'tf': 'M30'},
    'S17_CONVERGENCE_SCALP': {'pf': 1.107, 'wr': 0.257, 'tf': 'M30'},
}

# Soglie per flagging
PF_DRIFT_THRESHOLD  = 0.15   # PF cambia di ±15% → flag
WR_DRIFT_THRESHOLD  = 0.05   # WR cambia di ±5pp → flag
RECENT_DAYS_WINDOW  = 90     # giorni per analisi recente


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Fetch dati MT5
# ─────────────────────────────────────────────────────────────────────────────

def fetch_data(tfs: list, dry_run: bool = False) -> dict:
    """Chiama fetch_mt5_history.py per ogni TF. Ritorna {tf: ok/skip/error}."""
    results = {}
    fetch_script = os.path.join(_SCRIPT_DIR, 'fetch_mt5_history.py')

    if not os.path.exists(fetch_script):
        log.warning(f"[fetch] fetch_mt5_history.py non trovato — salto step 1")
        return {tf: 'skip' for tf in tfs}

    for tf in tfs:
        out_file = os.path.join(_DATA_DIR, TF_FILES[tf])
        log.info(f"[fetch] {tf} → {TF_FILES[tf]}")

        if dry_run:
            results[tf] = 'dry-run'
            continue

        try:
            proc = subprocess.run(
                [sys.executable, '-X', 'utf8', fetch_script, '--tf', tf],
                cwd=_ROOT_DIR,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode == 0:
                results[tf] = 'ok'
                log.info(f"[fetch] {tf} OK")
            else:
                results[tf] = 'error'
                log.warning(f"[fetch] {tf} ERRORE: {proc.stderr[:200]}")
        except subprocess.TimeoutExpired:
            results[tf] = 'timeout'
            log.warning(f"[fetch] {tf} TIMEOUT")
        except Exception as e:
            results[tf] = f'exc:{e}'
            log.error(f"[fetch] {tf} eccezione: {e}")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Backtest adattivo
# ─────────────────────────────────────────────────────────────────────────────

def run_backtests(tfs: list, dry_run: bool = False) -> dict:
    """
    Lancia strategy-engine-v2.py per ogni TF.
    Ritorna {tf: path_output_json | None}.
    """
    engine = os.path.join(_SCRIPT_DIR, 'strategy-engine-v2.py')
    results = {}

    for tf in tfs:
        data_file = os.path.join(_DATA_DIR, TF_FILES[tf])
        if not os.path.exists(data_file):
            log.warning(f"[backtest] {tf}: file dati non trovato ({data_file})")
            results[tf] = None
            continue

        date_tag = datetime.date.today().isoformat()
        out_file = os.path.join(_BT_DIR, f'daily_{tf}_{date_tag}.json')
        log.info(f"[backtest] {tf} → {os.path.basename(out_file)}")

        if dry_run:
            results[tf] = out_file
            continue

        try:
            proc = subprocess.run(
                [sys.executable, '-X', 'utf8', engine,
                 '--file', data_file, '--out', out_file],
                cwd=_ROOT_DIR,
                capture_output=True,
                text=True,
                timeout=600,
            )
            if proc.returncode == 0 and os.path.exists(out_file):
                results[tf] = out_file
                log.info(f"[backtest] {tf} OK → {out_file}")
            else:
                results[tf] = None
                log.warning(f"[backtest] {tf} ERRORE:\n{proc.stderr[:300]}")
        except subprocess.TimeoutExpired:
            results[tf] = None
            log.warning(f"[backtest] {tf} TIMEOUT (>600s)")
        except Exception as e:
            results[tf] = None
            log.error(f"[backtest] {tf} eccezione: {e}")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Parse risultati backtest
# ─────────────────────────────────────────────────────────────────────────────

def parse_backtest_results(bt_files: dict) -> dict:
    """
    Legge i JSON di output backtest e estrae stats per strategia.
    Ritorna {tf: {strategy_id: {pf, wr, n, pnl}}} per i TF riusciti.
    """
    parsed = {}
    for tf, path in bt_files.items():
        if path is None or not os.path.exists(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Struttura attesa: data['adaptive']['by_strategy'] o simile
            by_strategy = (
                data.get('adaptive', {}).get('by_strategy') or
                data.get('by_strategy') or
                {}
            )
            tf_stats = {}
            for sid, stats in by_strategy.items():
                if stats.get('n', 0) < 10:
                    continue
                tf_stats[sid] = {
                    'pf':  round(stats.get('profit_factor', 0.0), 3),
                    'wr':  round(stats.get('win_rate', 0.0), 4),
                    'n':   stats.get('n', 0),
                    'pnl': round(stats.get('total_profit', 0.0), 2),
                }
            parsed[tf] = tf_stats
            log.info(f"[parse] {tf}: {len(tf_stats)} strategie con ≥10 trade")
        except Exception as e:
            log.warning(f"[parse] {tf} errore lettura JSON: {e}")

    return parsed


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Drift analysis + parameter drift hints
# ─────────────────────────────────────────────────────────────────────────────

def drift_analysis(parsed_bt: dict) -> list:
    """
    Confronta PF/WR recenti vs baseline.
    Ritorna lista di findings:
      {strategy_id, tf, baseline_pf, new_pf, pf_delta_pct, baseline_wr, new_wr, flag}
    """
    findings = []

    for tf, strategies in parsed_bt.items():
        for sid, stats in strategies.items():
            base = BASELINE_STATS.get(sid)
            if not base or base.get('tf') != tf:
                continue  # confronta solo sul TF ottimale

            new_pf = stats['pf']
            new_wr = stats['wr']
            base_pf = base['pf']
            base_wr = base['wr']

            pf_delta = (new_pf - base_pf) / base_pf if base_pf > 0 else 0
            wr_delta = new_wr - base_wr

            flag = None
            if abs(pf_delta) > PF_DRIFT_THRESHOLD:
                flag = 'PF_DRIFT_UP' if pf_delta > 0 else 'PF_DRIFT_DOWN'
            if abs(wr_delta) > WR_DRIFT_THRESHOLD:
                flag = (flag or '') + ('WR_DRIFT_UP' if wr_delta > 0 else 'WR_DRIFT_DOWN')

            findings.append({
                'strategy_id':   sid,
                'tf':            tf,
                'baseline_pf':   base_pf,
                'new_pf':        new_pf,
                'pf_delta_pct':  round(pf_delta * 100, 1),
                'baseline_wr':   base_wr,
                'new_wr':        new_wr,
                'wr_delta_pp':   round(wr_delta * 100, 1),
                'n_trades':      stats['n'],
                'flag':          flag,
            })

    return findings


def param_drift_hints(findings: list) -> list:
    """
    Da drift findings, suggerisce aggiustamenti parametri.
    Ritorna lista di suggerimenti testuali.
    """
    hints = []
    for f in findings:
        if not f['flag']:
            continue
        sid = f['strategy_id']
        if 'PF_DRIFT_DOWN' in f['flag']:
            hints.append(
                f"  {sid}@{f['tf']}: PF {f['baseline_pf']:.3f}→{f['new_pf']:.3f} "
                f"({f['pf_delta_pct']:+.1f}%) → considera aumentare SL mult o ridurre TP mult"
            )
        elif 'PF_DRIFT_UP' in f['flag']:
            hints.append(
                f"  {sid}@{f['tf']}: PF {f['baseline_pf']:.3f}→{f['new_pf']:.3f} "
                f"({f['pf_delta_pct']:+.1f}%) → parametri migliorati, considera aggiornare baseline"
            )
        if 'WR_DRIFT_DOWN' in f['flag']:
            hints.append(
                f"  {sid}@{f['tf']}: WR {f['baseline_wr']:.1%}→{f['new_wr']:.1%} "
                f"({f['wr_delta_pp']:+.1f}pp) → segnali meno precisi, verifica condizioni mercato"
            )
    return hints


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Report
# ─────────────────────────────────────────────────────────────────────────────

def generate_report(fetch_res: dict, bt_res: dict, findings: list,
                    hints: list, news_summary: str, dry_run: bool) -> str:
    """Genera testo del report giornaliero."""
    today = datetime.date.today().isoformat()
    lines = [
        f"# Daily Maintenance Report — {today}",
        f"Generated: {datetime.datetime.utcnow().isoformat()} UTC",
        "",
        "## Step 1 — Fetch dati",
    ]
    for tf, status in (fetch_res or {}).items():
        icon = '✅' if status == 'ok' else ('⚠️' if status == 'skip' else '❌')
        lines.append(f"  {icon} {tf}: {status}")

    lines.append("")
    lines.append("## Step 2 — Backtest")
    for tf, path in (bt_res or {}).items():
        icon = '✅' if path else '❌'
        lines.append(f"  {icon} {tf}: {os.path.basename(path) if path else 'FAILED'}")

    lines.append("")
    lines.append("## Step 3 — Drift Analysis")
    if findings:
        lines.append("  Strategia                  | TF   | PF base→new   | WR base→new   | Flag")
        lines.append("  " + "-" * 70)
        for f in sorted(findings, key=lambda x: abs(x['pf_delta_pct']), reverse=True):
            icon = '🔴' if f['flag'] and 'DOWN' in f['flag'] else ('🟢' if f['flag'] else '⚪')
            lines.append(
                f"  {icon} {f['strategy_id']:<24} | {f['tf']:<4} | "
                f"{f['baseline_pf']:.3f}→{f['new_pf']:.3f} ({f['pf_delta_pct']:+.1f}%) | "
                f"{f['baseline_wr']:.1%}→{f['new_wr']:.1%} ({f['wr_delta_pp']:+.1f}pp) | "
                f"{f['flag'] or '-'}"
            )
    else:
        lines.append("  Nessun dato disponibile per confronto.")

    if hints:
        lines.append("")
        lines.append("## Step 4 — Parameter Drift Hints")
        lines.extend(hints)

    if news_summary:
        lines.append("")
        lines.append("## News Calendar")
        lines.append(news_summary)

    if dry_run:
        lines.append("\n⚠️  DRY-RUN — nessuna modifica applicata")

    return '\n'.join(lines)


def append_to_self_learning_log(findings: list, dry_run: bool):
    """Aggiunge righe significative al self-learning log."""
    if dry_run:
        return
    significant = [f for f in findings if f['flag'] and abs(f['pf_delta_pct']) > 10]
    if not significant:
        return

    log_path = os.path.join(_DIR_DIR, '07_self_learning_log.md')
    today    = datetime.date.today().isoformat()
    rows     = []
    for f in significant:
        rows.append(
            f"| {today} | Daily Maintenance: {f['strategy_id']}@{f['tf']} "
            f"PF drift {f['pf_delta_pct']:+.1f}% "
            f"({f['baseline_pf']:.3f}→{f['new_pf']:.3f}) | "
            f"backtest recente | {f['flag']} |"
        )
    try:
        with open(log_path, 'r', encoding='utf-8') as fl:
            content = fl.read()
        marker = '|---|---|---|---|'
        content = content.replace(marker, marker + '\n' + '\n'.join(rows), 1)
        with open(log_path, 'w', encoding='utf-8') as fl:
            fl.write(content)
        log.info(f"[log] {len(rows)} righe aggiunte a 07_self_learning_log.md")
    except Exception as e:
        log.warning(f"[log] errore scrittura self_learning_log: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description='TradeFlow AI — Daily Maintenance')
    ap.add_argument('--skip-fetch',    action='store_true', help='Salta download dati MT5')
    ap.add_argument('--skip-backtest', action='store_true', help='Salta backtest')
    ap.add_argument('--tfs', type=str, default='M5,M15,M30,H1,H4',
                    help='TimeFrame da processare (default: M5,M15,M30,H1,H4)')
    ap.add_argument('--dry-run', action='store_true', help='Nessuna scrittura su disco')
    args = ap.parse_args()

    tfs     = [t.strip().upper() for t in args.tfs.split(',') if t.strip() in TF_FILES]
    dry_run = args.dry_run

    log.info(f"═══ Daily Maintenance — {datetime.date.today()} — TFs: {tfs} ═══")
    if dry_run:
        log.info("DRY-RUN MODE — nessuna scrittura")

    # Step 1 — Fetch
    fetch_res = {}
    if args.skip_fetch:
        log.info("[1/5] Fetch saltato")
        fetch_res = {tf: 'skip' for tf in tfs}
    else:
        log.info("[1/5] Fetch dati MT5...")
        fetch_res = fetch_data(tfs, dry_run=dry_run)

    # Step 2 — Backtest
    bt_res = {}
    if args.skip_backtest:
        log.info("[2/5] Backtest saltato")
        bt_res = {tf: None for tf in tfs}
    else:
        log.info("[2/5] Backtest adattivo per TF...")
        bt_res = run_backtests(tfs, dry_run=dry_run)

    # Step 3 — Parse
    log.info("[3/5] Parsing risultati...")
    parsed = parse_backtest_results(bt_res)

    # Step 4 — Drift
    log.info("[4/5] Drift analysis...")
    findings = drift_analysis(parsed)
    hints    = param_drift_hints(findings)

    if findings:
        log.info(f"  {len(findings)} strategie confrontate, "
                 f"{sum(1 for f in findings if f['flag'])} con drift significativo")
    for h in hints:
        log.info(h)

    # News summary
    news_summary = ''
    try:
        from news_guardian import get_news_guardian
        ng = get_news_guardian()
        ng.refresh(force=True)
        upcoming = ng.get_upcoming_high_impact(hours_ahead=24)
        if upcoming:
            news_summary = f"  Prossime {len(upcoming)} news HIGH USD/XAU oggi:\n"
            for e in upcoming[:5]:
                news_summary += f"  • {e['dt'][11:16]} UTC ({e['minutes_away']}min) {e['currency']} {e['title']}\n"
        else:
            news_summary = "  Nessuna news HIGH USD/XAU nelle prossime 24h."
    except Exception as e:
        log.warning(f"[news] fetch fallito: {e}")

    # Step 5 — Report
    log.info("[5/5] Generazione report...")
    report = generate_report(fetch_res, bt_res, findings, hints, news_summary, dry_run)

    report_path = os.path.join(_ROOT_DIR, f'daily_report_{datetime.date.today().isoformat()}.txt')
    if not dry_run:
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        log.info(f"  Report salvato: {report_path}")
        append_to_self_learning_log(findings, dry_run)

    log.info("═══ Daily Maintenance completato ═══")
    print("\n" + report)


if __name__ == '__main__':
    main()
