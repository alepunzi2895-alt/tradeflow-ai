"""
TradeFlow AI — Daily Maintenance Script
═══════════════════════════════════════════════════════════════════
Da eseguire ogni giorno sulla VPS (es. 06:00 UTC via Task Scheduler).

Step 1 — Fetch dati storici MT5 per ogni TF (richiede MT5 aperto)
Step 2 — Backtest adattivo su ogni TF (strategy-engine-v2.py)
Step 3 — Parse risultati + drift analysis (confronta PF/WR recenti vs baseline)
Step 4 — Trade silence check: giorni senza trade live per strategia (da mt5-trades.json)
Step 5 — AI Root-Cause Review: diagnosi automatica anomalie via Claude (advisory-only,
          vedi directives/09_ai_review_agents.md — non modifica mai codice/parametri)
Step 6 — Genera report giornaliero, logga in 07_self_learning_log.md e 06_known_issues.md

USO:
  python scripts/daily_maintenance.py
  python scripts/daily_maintenance.py --skip-fetch       # salta fetch MT5
  python scripts/daily_maintenance.py --skip-backtest    # salta backtest
  python scripts/daily_maintenance.py --skip-ai-review   # salta diagnosi AI (Step 5)
  python scripts/daily_maintenance.py --tfs M30,H1,H4   # solo TF specifici
  python scripts/daily_maintenance.py --dry-run          # nessuna scrittura

Task Scheduler Windows (ogni giorno alle 06:00):
  Action: python -X utf8 C:\\path\\to\\scripts\\daily_maintenance.py
  Start in: C:\\path\\to\\tradeflow-ai
"""
import sys, io, os, json, subprocess, datetime, logging, argparse, math, inspect

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
# NOTA (2026-07-09): S16 e S17 erano disallineate rispetto a BASELINE_STATS e a
# directives/02_strategies.md — bug di staleness scoperto dalla AI Root-Cause
# Review (Feature A, primo run reale) mentre diagnosticava un TRADE_SILENCE su
# S17. Questo dict era dead code nello script originale (mai consumato prima
# di check_trade_silence()), quindi il disallineamento non aveva mai avuto
# effetto — ora che viene letto va tenuto sincronizzato con BASELINE_STATS.
STRATEGY_OPTIMAL_TF = {
    'S00_MFKK':              'M30',
    'S05_MFKK_INTRADAY':     'H1',
    'S09_MFKK_SCALPING':     'M30',
    'S10_OB_FVG_SCALP':      'M30',
    'S16_GOLDEN_SQUEEZE':    'H1',
    'S17_CONVERGENCE_SCALP': 'H4',
}

# Baseline backtest completo (fonte di verità, aggiornato dopo ogni campagna)
# Fonte: adaptive.by_strategy bt_*_v6final — 2026-04-30
BASELINE_STATS = {
    'S00_MFKK':              {'pf': 1.628, 'wr': 0.494, 'tf': 'M30'},
    'S05_MFKK_INTRADAY':     {'pf': 1.046, 'wr': 0.253, 'tf': 'H1'},
    'S09_MFKK_SCALPING':     {'pf': 1.761, 'wr': 0.302, 'tf': 'M30'},
    'S10_OB_FVG_SCALP':      {'pf': 2.130, 'wr': 0.519, 'tf': 'M30'},
    'S16_GOLDEN_SQUEEZE':    {'pf': 2.120, 'wr': 0.514, 'tf': 'H1'},
    'S17_CONVERGENCE_SCALP': {'pf': 2.641, 'wr': 0.340, 'tf': 'H4'},
}

# Soglie per flagging
PF_DRIFT_THRESHOLD  = 0.15   # PF cambia di ±15% → flag
WR_DRIFT_THRESHOLD  = 0.05   # WR cambia di ±5pp → flag
RECENT_DAYS_WINDOW  = 90     # giorni per analisi recente

# ── Trade Silence Check (Step 4) ──────────────────────────────────────────────
TRADES_FILE = os.path.join(_ROOT_DIR, 'mt5-trades.json')

# Mapping strategy_id → nome funzione segnale in signals.py (per raccolta contesto AI)
STRATEGY_SIGNAL_FN = {
    'S00_MFKK':              'signal_mfkk_score',
    'S05_MFKK_INTRADAY':     'signal_mfkk_intraday',
    'S09_MFKK_SCALPING':     'signal_mfkk_scalping',
    'S10_OB_FVG_SCALP':      'signal_ob_fvg_scalp',
    'S16_GOLDEN_SQUEEZE':    'signal_golden_squeeze',
    'S17_CONVERGENCE_SCALP': 'signal_convergence_scalp',
}

# Soglia "silenzio" per-strategia: strategie su TF più alti hanno frequenza di
# trade nativamente più bassa (es. S17 su H4 ≈ 1 trade ogni 7-8gg in backtest) —
# una soglia unica globale creerebbe falsi positivi costanti su quelle.
# Valori iniziali conservativi, da ricalibrare con qualche settimana di dati
# reali (vedi directives/09_ai_review_agents.md). Anche a 7-14gg, il bug reale
# del 2026-07-07 (quality_gate RSI>75, 2.5 mesi di silenzio) sarebbe stato
# flaggato entro la prima settimana.
STRATEGY_SILENCE_THRESHOLD_DAYS = {
    'S00_MFKK':              7,
    'S05_MFKK_INTRADAY':     10,
    'S09_MFKK_SCALPING':     7,
    'S10_OB_FVG_SCALP':      7,
    'S16_GOLDEN_SQUEEZE':    10,
    'S17_CONVERGENCE_SCALP': 14,
}
DEFAULT_SILENCE_THRESHOLD_DAYS = 7


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
# STEP 4 — Trade Silence Check
# ─────────────────────────────────────────────────────────────────────────────

def check_trade_silence(threshold_map: dict = None) -> list:
    """
    Legge mt5-trades.json (root, schema {time, direction, strategy, ...} — NON
    ha un campo 'profit': è un check di presenza/assenza, non di performance).
    Per ogni strategia attiva (STRATEGY_OPTIMAL_TF), calcola giorni dall'ultimo
    trade e confronta con la soglia per-strategia.

    Ritorna SOLO le strategie in silenzio:
      [{strategy_id, tf, last_trade: iso|None, days_since: int|None,
        threshold_days: int, flag: 'TRADE_SILENCE'}]
    Fail-open: file mancante/malformato → log warning, ritorna [].
    """
    threshold_map = threshold_map or STRATEGY_SILENCE_THRESHOLD_DAYS

    if not os.path.exists(TRADES_FILE):
        log.warning(f"[silence] {TRADES_FILE} non trovato — salto trade silence check")
        return []

    try:
        with open(TRADES_FILE, 'r', encoding='utf-8') as f:
            trades = json.load(f)
    except Exception as e:
        log.warning(f"[silence] errore lettura {TRADES_FILE}: {e}")
        return []

    last_trade_by_strategy = {}
    for t in trades:
        sid = t.get('strategy')
        ts = t.get('time')
        if not sid or not ts:
            continue
        try:
            dt = datetime.datetime.fromisoformat(ts.replace('Z', '+00:00'))
        except ValueError:
            continue
        if sid not in last_trade_by_strategy or dt > last_trade_by_strategy[sid]:
            last_trade_by_strategy[sid] = dt

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    findings = []
    for sid, tf in STRATEGY_OPTIMAL_TF.items():
        threshold = threshold_map.get(sid, DEFAULT_SILENCE_THRESHOLD_DAYS)
        last = last_trade_by_strategy.get(sid)
        if last is None:
            findings.append({
                'strategy_id': sid, 'tf': tf, 'last_trade': None,
                'days_since': None, 'threshold_days': threshold,
                'flag': 'TRADE_SILENCE',
            })
            continue
        days_since = (now_utc - last).days
        if days_since >= threshold:
            findings.append({
                'strategy_id': sid, 'tf': tf, 'last_trade': last.isoformat(),
                'days_since': days_since, 'threshold_days': threshold,
                'flag': 'TRADE_SILENCE',
            })

    return findings


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — AI Root-Cause Review (advisory-only, mai modifica codice/parametri)
# ─────────────────────────────────────────────────────────────────────────────

def _grep_signal_source(strategy_id: str) -> str:
    """Sorgente della funzione signal_* pertinente via inspect.getsource. Fail-open: '' su errore."""
    fn_name = STRATEGY_SIGNAL_FN.get(strategy_id)
    if not fn_name:
        return ''
    try:
        import signals
        fn = getattr(signals, fn_name, None)
        if fn is None:
            return ''
        return inspect.getsource(fn)
    except Exception as e:
        log.warning(f"[ai-review] impossibile leggere sorgente {fn_name}: {e}")
        return ''


def _grep_self_learning_log(strategy_id: str, max_lines: int = 8) -> list:
    """
    Righe della tabella di 07_self_learning_log.md che contengono strategy_id.
    Il file NON è in ordine cronologico stretto (le insert avvengono subito dopo
    l'header, non in coda) — ordina per la prima colonna (data ISO) discendente
    prima di troncare, invece di assumere "ultime righe del file" = "più recenti".
    """
    log_path = os.path.join(_DIR_DIR, '07_self_learning_log.md')
    if not os.path.exists(log_path):
        return []
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        log.warning(f"[ai-review] errore lettura self_learning_log: {e}")
        return []

    matches = []
    for line in lines:
        if not line.startswith('|') or strategy_id not in line:
            continue
        parts = line.split('|')
        date_str = parts[1].strip() if len(parts) > 1 else ''
        matches.append((date_str, line.rstrip('\n')))

    matches.sort(key=lambda x: x[0], reverse=True)
    return [line for _, line in matches[:max_lines]]


def _recent_commits(paths: list, n: int = 10) -> list:
    """git log --oneline -n <n> -- <path...>. Fail-open: [] su qualunque errore/timeout."""
    try:
        proc = subprocess.run(
            ['git', 'log', '--oneline', f'-{n}', '--', *paths],
            cwd=_ROOT_DIR, capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            return []
        return [l for l in proc.stdout.splitlines() if l.strip()]
    except Exception:
        return []


AI_DIAGNOSIS_SYSTEM_PROMPT = """Sei un senior quant developer che fa da secondo paio d'occhi su un bot di trading algoritmico XAU/USD scritto in Python (MetaTrader5). Il tuo compito è SOLO diagnosi: non proponi modifiche automatiche, non hai accesso a strumenti di scrittura o esecuzione codice.

Rispondi SEMPRE con un singolo oggetto JSON valido, senza markdown fences, con ESATTAMENTE questi campi:
{
  "root_cause": "<ipotesi principale in italiano, 1-3 frasi>",
  "confidence": <float 0.0-1.0>,
  "suspect_file": "<path relativo, es. scripts/signals.py>",
  "suspect_function": "<nome funzione o 'N/A'>",
  "suggested_fix": "<suggerimento testuale conciso, MAI codice completo>",
  "requires_human_review": <true|false>
}
Se non hai contesto sufficiente per un'ipotesi solida, imposta confidence<0.3 e spiega nel root_cause cosa servirebbe per investigare oltre — NON inventare cause.

Contesto di progetto importante: un bug reale (quality_gate RSI>75) ha bloccato tutti i buy live per 2.5 mesi pur passando indenne il backtest, perché quel gate esiste SOLO nel codice di esecuzione live (mt5-bot.py) e non nel backtester. Quando la finding è di tipo TRADE_SILENCE, considera esplicitamente l'ipotesi che un filtro/gate lato esecuzione live blocchi il segnale anche se la logica "pura" del segnale (signals.py) e il backtest risultano sani."""


def build_diagnosis_prompt(finding: dict, context: dict) -> tuple:
    """Ritorna (system_prompt, user_prompt) per una singola finding."""
    sid = finding['strategy_id']
    tf = finding.get('tf', '?')
    today = datetime.date.today().isoformat()

    if finding['flag'] == 'TRADE_SILENCE':
        detail = (
            f"Ultimo trade: {finding.get('last_trade') or 'MAI (nessun trade registrato)'}\n"
            f"Giorni dall'ultimo trade: {finding.get('days_since', 'N/D')}\n"
            f"Soglia di silenzio per questa strategia: {finding['threshold_days']} giorni"
        )
    else:
        detail = (
            f"PF baseline→nuovo: {finding.get('baseline_pf')}→{finding.get('new_pf')} "
            f"({finding.get('pf_delta_pct')}%)\n"
            f"WR baseline→nuovo: {finding.get('baseline_wr')}→{finding.get('new_wr')} "
            f"({finding.get('wr_delta_pp')}pp)\n"
            f"Trade nel campione: {finding.get('n_trades')}"
        )

    signal_src = context.get('signal_source') or 'N/D — funzione non trovata/non importabile'
    log_rows = context.get('log_rows') or []
    log_text = '\n'.join(log_rows) if log_rows else 'Nessuna riga storica trovata per questo strategy_id'
    commits = context.get('commits') or []
    commits_text = '\n'.join(commits) if commits else 'Nessun commit trovato'

    user = f"""ANOMALIA RILEVATA — {today}
Tipo: {finding['flag']}   Strategia: {sid}   TF canonico: {tf}

--- Dettaglio finding ---
{detail}

--- Codice funzione segnale (scripts/signals.py::{STRATEGY_SIGNAL_FN.get(sid, 'N/D')}) ---
{signal_src}

--- Righe pertinenti da directives/07_self_learning_log.md ---
{log_text}

--- Ultimi commit su scripts/signals.py e scripts/mt5-bot.py ---
{commits_text}

Fornisci la diagnosi nel formato JSON richiesto dal system prompt."""

    return AI_DIAGNOSIS_SYSTEM_PROMPT, user


def run_ai_diagnosis(to_diagnose: list) -> list:
    """
    Per ogni finding (drift o silenzio), raccoglie contesto e chiama Claude.
    Import lazy di ai_review — un problema nel modulo (es. requests mancante)
    non deve impedire l'avvio dell'intero script di manutenzione.

    Ritorna lista di dict: {strategy_id, flag, ok, diagnosis|error}
    """
    try:
        import ai_review
    except ImportError as e:
        log.warning(f"[ai-review] modulo ai_review non disponibile ({e}) — skip diagnosi AI")
        return [{'strategy_id': f['strategy_id'], 'flag': f['flag'], 'ok': False,
                  'error': f'modulo ai_review non disponibile: {e}'} for f in to_diagnose]

    if not ai_review.is_configured():
        log.warning("[ai-review] ANTHROPIC_API_KEY mancante — skip diagnosi AI")
        return [{'strategy_id': f['strategy_id'], 'flag': f['flag'], 'ok': False,
                  'error': 'ANTHROPIC_API_KEY mancante'} for f in to_diagnose]

    results = []
    for finding in to_diagnose:
        sid = finding['strategy_id']
        try:
            context = {
                'signal_source': _grep_signal_source(sid),
                'log_rows': _grep_self_learning_log(sid),
                'commits': _recent_commits(['scripts/signals.py', 'scripts/mt5-bot.py']),
            }
            system, user = build_diagnosis_prompt(finding, context)
            parsed, err = ai_review.call_claude_json(
                system, user, max_tokens=4000, thinking='adaptive', timeout=60,
            )
            if err:
                log.warning(f"[ai-review] diagnosi fallita per {sid}: {err}")
                results.append({'strategy_id': sid, 'flag': finding['flag'], 'ok': False, 'error': err})
            else:
                log.info(f"[ai-review] diagnosi ricevuta per {sid} (confidence={parsed.get('confidence')})")
                results.append({'strategy_id': sid, 'flag': finding['flag'], 'ok': True, 'diagnosis': parsed})
        except Exception as e:
            log.warning(f"[ai-review] eccezione imprevista per {sid}: {e} (fail-open, continuo con le altre)")
            results.append({'strategy_id': sid, 'flag': finding['flag'], 'ok': False, 'error': str(e)})

    return results


def append_ai_findings_to_known_issues(diagnoses: list, dry_run: bool):
    """
    Appende righe '🤖 AI-Flagged <data>' a directives/06_known_issues.md (Bug Aperti)
    per ogni diagnosi riuscita. Dedup: salta se esiste già una riga con lo stesso
    tag-data + strategy_id (evita duplicati su run ripetute lo stesso giorno).
    """
    if dry_run:
        return

    ok_diagnoses = [d for d in diagnoses if d.get('ok')]
    if not ok_diagnoses:
        return

    known_path = os.path.join(_DIR_DIR, '06_known_issues.md')
    if not os.path.exists(known_path):
        log.warning(f"[ai-review] {known_path} non trovato — salto append")
        return

    today = datetime.date.today().isoformat()
    tag = f"🤖 AI-Flagged {today}"

    try:
        with open(known_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        log.warning(f"[ai-review] errore lettura known_issues: {e}")
        return

    new_rows = []
    for d in ok_diagnoses:
        sid = d['strategy_id']
        if tag in content and sid in content:
            # Dedup approssimativo: se tag+sid appaiono già da qualche parte nel file
            # (tipicamente nella stessa riga appesa in un run precedente), salta.
            existing_lines = [l for l in content.splitlines() if tag in l and sid in l]
            if existing_lines:
                log.info(f"[ai-review] riga già presente per {sid}@{today} — skip dedup")
                continue

        diag = d['diagnosis']
        row = (
            f"| {tag} | `{diag.get('suspect_file', 'N/D')}` | "
            f"**{sid}** {d['flag']}: {diag.get('root_cause', 'N/D')} "
            f"(confidenza {round(diag.get('confidence', 0) * 100)}%, "
            f"funzione sospetta `{diag.get('suspect_function', 'N/A')}`). "
            f"Suggerimento: {diag.get('suggested_fix', 'N/D')} |"
        )
        new_rows.append(row)

    if not new_rows:
        return

    marker_section = '## Bug Aperti'
    idx = content.find(marker_section)
    if idx == -1:
        log.warning("[ai-review] sezione '## Bug Aperti' non trovata in known_issues.md — salto append")
        return

    marker_sep = '|---|---|---|'
    sep_idx = content.find(marker_sep, idx)
    if sep_idx == -1:
        log.warning("[ai-review] separatore tabella non trovato dopo '## Bug Aperti' — salto append")
        return

    insert_at = sep_idx + len(marker_sep)
    content = content[:insert_at] + '\n' + '\n'.join(new_rows) + content[insert_at:]

    try:
        with open(known_path, 'w', encoding='utf-8') as f:
            f.write(content)
        log.info(f"[ai-review] {len(new_rows)} righe aggiunte a 06_known_issues.md")
    except Exception as e:
        log.warning(f"[ai-review] errore scrittura known_issues: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Report
# ─────────────────────────────────────────────────────────────────────────────

def generate_report(fetch_res: dict, bt_res: dict, findings: list,
                    hints: list, silence_findings: list, diagnoses: list,
                    news_summary: str, dry_run: bool) -> str:
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
        lines.append("## Step 3b — Parameter Drift Hints")
        lines.extend(hints)

    lines.append("")
    lines.append("## Step 4 — Trade Silence Check")
    if silence_findings:
        for sf in silence_findings:
            last = sf['last_trade'] or 'MAI'
            lines.append(
                f"  🔴 {sf['strategy_id']:<24} | {sf['tf']:<4} | ultimo trade: {last} | "
                f"{sf['days_since'] if sf['days_since'] is not None else '∞'} gg "
                f"(soglia {sf['threshold_days']}gg)"
            )
    else:
        lines.append("  ✅ Tutte le strategie attive hanno trade recenti.")

    lines.append("")
    lines.append("## Step 5 — AI Root-Cause Review")
    if diagnoses:
        for d in diagnoses:
            if d.get('ok'):
                diag = d['diagnosis']
                lines.append(
                    f"  🤖 {d['strategy_id']} ({d['flag']}): {diag.get('root_cause', 'N/D')}\n"
                    f"      Confidenza: {round(diag.get('confidence', 0) * 100)}% | "
                    f"File sospetto: {diag.get('suspect_file', 'N/D')} :: {diag.get('suspect_function', 'N/A')}\n"
                    f"      Suggerimento: {diag.get('suggested_fix', 'N/D')}"
                )
            else:
                lines.append(f"  ⚠️  {d['strategy_id']} ({d['flag']}): diagnosi non disponibile — {d.get('error', 'errore sconosciuto')}")
    else:
        lines.append("  Nessuna anomalia da diagnosticare — API non chiamata.")

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
    ap.add_argument('--skip-ai-review', action='store_true',
                    help='Salta la diagnosi AI (Step 5) — nessuna chiamata API')
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
        log.info("[1/6] Fetch saltato")
        fetch_res = {tf: 'skip' for tf in tfs}
    else:
        log.info("[1/6] Fetch dati MT5...")
        fetch_res = fetch_data(tfs, dry_run=dry_run)

    # Step 2 — Backtest
    bt_res = {}
    if args.skip_backtest:
        log.info("[2/6] Backtest saltato")
        bt_res = {tf: None for tf in tfs}
    else:
        log.info("[2/6] Backtest adattivo per TF...")
        bt_res = run_backtests(tfs, dry_run=dry_run)

    # Step 3 — Parse + Drift
    log.info("[3/6] Parsing risultati + drift analysis...")
    parsed = parse_backtest_results(bt_res)
    findings = drift_analysis(parsed)
    hints    = param_drift_hints(findings)

    if findings:
        log.info(f"  {len(findings)} strategie confrontate, "
                 f"{sum(1 for f in findings if f['flag'])} con drift significativo")
    for h in hints:
        log.info(h)

    # Step 4 — Trade Silence Check
    log.info("[4/6] Trade silence check...")
    silence_findings = check_trade_silence()
    if silence_findings:
        log.info(f"  {len(silence_findings)} strategie in silenzio: "
                 f"{', '.join(sf['strategy_id'] for sf in silence_findings)}")
    else:
        log.info("  Tutte le strategie attive hanno trade recenti")

    # Step 5 — AI Root-Cause Review (advisory-only)
    log.info("[5/6] AI Root-Cause Review...")
    to_diagnose = [f for f in findings if f['flag']] + silence_findings
    diagnoses = []
    if args.skip_ai_review:
        log.info("  Saltato (--skip-ai-review)")
    elif not to_diagnose:
        log.info("  Nessuna anomalia da diagnosticare — API non chiamata")
    else:
        try:
            diagnoses = run_ai_diagnosis(to_diagnose)
        except Exception as e:
            log.warning(f"[ai-review] eccezione imprevista nello step 5: {e} (fail-open)")

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

    # Step 6 — Report
    log.info("[6/6] Generazione report...")
    report = generate_report(fetch_res, bt_res, findings, hints,
                              silence_findings, diagnoses, news_summary, dry_run)

    report_path = os.path.join(_ROOT_DIR, f'daily_report_{datetime.date.today().isoformat()}.txt')
    if not dry_run:
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        log.info(f"  Report salvato: {report_path}")
        append_to_self_learning_log(findings, dry_run)
        append_ai_findings_to_known_issues(diagnoses, dry_run)

    log.info("═══ Daily Maintenance completato ═══")
    print("\n" + report)


if __name__ == '__main__':
    main()
