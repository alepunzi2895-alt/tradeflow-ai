"""
TradeFlow AI — Reactivation Check (mensile)
═══════════════════════════════════════════════════════════════════
Verifica se le strategie hard-bloccate (elencate in data/hard_blocks.json;
compat: score_mult=0.0 in data/strategy_overrides.json) hanno recuperato un
edge sufficiente nel backtest per essere ricandidate all'attivazione.

Perché serve un check separato, a backtest, e non basta il self-learning
già presente in performance_tracker.py: quel meccanismo ricalcola
score_mult sulla base del WR ROLLING sui trade LIVE recenti — ma una
strategia hard-bloccata smette di generare nuovi trade live (quality_gate
la filtra, vedi mt5-bot.py + strategy_selector.is_hard_blocked(), fix
2026-09-01), quindi non accumula mai gli >= MIN_TRADES_ADJUST trade
necessari per essere rivalutata: resterebbe bloccata per sempre anche se
il regime di mercato tornasse favorevole. Questo script chiude il loop:
ri-testa via BACKTEST (non serve storico live) ogni strategia bloccata sul
suo TF canonico e segnala se è tornata sopra soglia.

Advisory-only: non modifica MAI data/hard_blocks.json. Logga solo
un suggerimento in directives/07_self_learning_log.md — la riattivazione
resta una decisione umana (comporta rischio di capitale reale).

USO:
  python scripts/reactivation_check.py
  python scripts/reactivation_check.py --skip-fetch      # usa dati già scaricati
  python scripts/reactivation_check.py --dry-run         # nessuna scrittura

Task Scheduler Windows (1° di ogni mese, es. 07:00 UTC):
  Action:  python -X utf8 C:\\path\\to\\scripts\\reactivation_check.py
  Start in: C:\\path\\to\\tradeflow-ai
  Trigger: Monthly, day 1

  schtasks /create /tn "TradeFlowAI_ReactivationCheck" /tr "python -X utf8 C:\\path\\to\\tradeflow-ai\\scripts\\reactivation_check.py" /sc monthly /d 1 /st 07:00 /f
"""
import sys, os, json, datetime, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import daily_maintenance as dm  # imposta anche sys.stdout UTF-8 + logging condivisi
from performance_tracker import PENALTY_THRESHOLD, _ensure_auto_log  # PENALTY: WR/baseline >= 0.70 = fuori zona penalità

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR   = os.path.join(_SCRIPT_DIR, '..')
_DATA_DIR   = os.path.join(_ROOT_DIR, 'data')
_DIR_DIR    = os.path.join(_ROOT_DIR, 'directives')
_BT_DIR     = os.path.join(_ROOT_DIR, 'backtests', 'results')

OVERRIDES_PATH   = os.path.join(_DATA_DIR, 'strategy_overrides.json')
HARD_BLOCKS_PATH = os.path.join(_DATA_DIR, 'hard_blocks.json')

# S18_RANGE_REVERSAL bloccata 2026-09-01, non ancora presente nelle tabelle di
# daily_maintenance.py (aggiunte qui via merge invece di duplicare il modulo).
# Baseline coerente con performance_tracker.py::BACKTEST_BASELINES.
EXTRA_OPTIMAL_TF = {'S18_RANGE_REVERSAL': 'M30'}
EXTRA_BASELINE   = {'S18_RANGE_REVERSAL': {'pf': 1.35, 'wr': 0.450, 'tf': 'M30'}}

# Soglia "candidata alla riattivazione": WR tornato >= 70% del baseline
# (stessa soglia PENALTY_THRESHOLD di performance_tracker.py — sotto è ancora
# in zona di penalità, non ha senso riattivare) E PF>=1.2 (margine sopra
# breakeven, non solo "non più negativo").
REACTIVATION_WR_RATIO = PENALTY_THRESHOLD
REACTIVATION_MIN_PF   = 1.2


def load_blocked_strategies() -> dict:
    """{strategy_id: {updated_at, reason, ...}} per le strategie disabilitate live.

    Fonte primaria: data/hard_blocks.json (git-tracked, human-only — 2026-09-03).
    Fallback legacy: entry score_mult=0.0 in strategy_overrides.json non ancora migrate.
    """
    blocked = {}

    try:
        with open(HARD_BLOCKS_PATH, 'r', encoding='utf-8') as f:
            hb = json.load(f)
        for sid, meta in (hb.get('blocked', {}) or {}).items():
            meta = meta if isinstance(meta, dict) else {}
            blocked[sid] = {
                'updated_at': meta.get('since', '?'),
                'reason':     meta.get('reason', 'hard_blocks.json'),
            }
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[reactivation] errore lettura {HARD_BLOCKS_PATH}: {e}")

    if os.path.exists(OVERRIDES_PATH):
        try:
            with open(OVERRIDES_PATH, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            for sid, v in raw.items():
                if v.get('score_mult', 1.0) == 0.0 and sid not in blocked:
                    blocked[sid] = v
        except Exception as e:
            print(f"[reactivation] errore lettura {OVERRIDES_PATH}: {e}")

    return blocked


def check(skip_fetch: bool, dry_run: bool) -> list:
    blocked = load_blocked_strategies()
    if not blocked:
        print("[reactivation] Nessuna strategia bloccata — nulla da ri-testare.")
        return []

    optimal_tf = {**dm.STRATEGY_OPTIMAL_TF, **EXTRA_OPTIMAL_TF}
    baselines  = {**dm.BASELINE_STATS, **EXTRA_BASELINE}

    tfs_needed = sorted({optimal_tf[sid] for sid in blocked if sid in optimal_tf})
    if not tfs_needed:
        print(f"[reactivation] Strategie bloccate senza TF canonico noto: {list(blocked)} — skip.")
        return []

    print(f"[reactivation] Strategie bloccate: {list(blocked)} | TF da ri-testare: {tfs_needed}")

    if skip_fetch:
        print("[reactivation] Fetch saltato (--skip-fetch)")
    else:
        dm.fetch_data(tfs_needed, dry_run=dry_run)

    bt_res = dm.run_backtests(tfs_needed, dry_run=dry_run)
    parsed = dm.parse_backtest_results(bt_res)

    results = []
    for sid, override in blocked.items():
        tf = optimal_tf.get(sid)
        base = baselines.get(sid)
        if not tf or not base:
            print(f"[reactivation] {sid}: nessun TF/baseline noto — skip.")
            continue
        stats = (parsed.get(tf) or {}).get(sid)
        if not stats:
            print(f"[reactivation] {sid}@{tf}: campione insufficiente nel ri-test (n<10 o dati mancanti) — resta bloccata.")
            results.append({'strategy_id': sid, 'tf': tf, 'status': 'insufficient_sample'})
            continue

        wr_ratio = stats['wr'] / base['wr'] if base['wr'] > 0 else 0.0
        candidate = wr_ratio >= REACTIVATION_WR_RATIO and stats['pf'] >= REACTIVATION_MIN_PF

        print(
            f"[reactivation] {sid}@{tf}: WR {stats['wr']:.1%} (baseline {base['wr']:.1%}, "
            f"ratio {wr_ratio:.0%}) | PF {stats['pf']:.3f} | n={stats['n']} | "
            f"bloccata dal {override.get('updated_at', '?')[:10]} per: {override.get('reason', '?')} | "
            f"{'🔓 CANDIDATA ALLA RIATTIVAZIONE' if candidate else '⛔ resta bloccata'}"
        )
        results.append({
            'strategy_id': sid, 'tf': tf, 'status': 'candidate' if candidate else 'still_blocked',
            'new_wr': stats['wr'], 'new_pf': stats['pf'], 'n': stats['n'],
            'baseline_wr': base['wr'], 'wr_ratio': round(wr_ratio, 3),
            'blocked_since': override.get('updated_at', '?')[:10],
            'blocked_reason': override.get('reason', '?'),
        })

    return results


def append_report(results: list, dry_run: bool):
    if dry_run or not results:
        return
    today = datetime.date.today().isoformat()
    log_path = os.path.join(_DIR_DIR, '07_self_learning_auto.md')  # sidecar gitignored
    _ensure_auto_log(log_path)

    # Dedup: se oggi è già stata loggata una riga di questo tag, non duplicare
    # (es. run ripetuti manualmente lo stesso giorno).
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            existing = f.read()
        if any(today in line and 'reactivation_check' in line for line in existing.splitlines()):
            print(f"[reactivation] riga già presente per {today} — skip dedup")
            return
    except Exception:
        pass

    candidates = [r for r in results if r['status'] == 'candidate']
    if candidates:
        detail = '; '.join(
            f"{r['strategy_id']}@{r['tf']} WR {r['new_wr']:.1%} (ratio {r['wr_ratio']:.0%} vs baseline) PF {r['new_pf']:.3f} n={r['n']}"
            for r in candidates
        )
        bug = (
            f"**Reactivation Check mensile — {len(candidates)} strategia/e candidata/e alla riattivazione**: {detail}. "
            f"Bloccate dal self-learning il {candidates[0]['blocked_since']} per: {candidates[0]['blocked_reason']}. "
            f"**Advisory-only, nessuna modifica automatica a data/hard_blocks.json** — richiede revisione umana prima di sbloccare."
        )
    else:
        checked = ', '.join(f"{r['strategy_id']}@{r['tf']}" for r in results)
        bug = f"Reactivation Check mensile — nessuna strategia bloccata ha recuperato l'edge (soglia WR ratio≥{REACTIVATION_WR_RATIO:.0%} e PF≥{REACTIVATION_MIN_PF}). Verificate: {checked}."

    row = f"| {today} | {bug} | ri-test mensile automatico | reactivation_check |\n"
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            content = f.read()
        marker = '|---|---|---|---|'
        content = content.replace(marker, marker + '\n' + row.rstrip('\n'), 1)
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"[reactivation] riga aggiunta a {log_path}")
    except Exception as e:
        print(f"[reactivation] errore scrittura self_learning_log: {e}")


def main():
    ap = argparse.ArgumentParser(description='TradeFlow AI — Reactivation Check (mensile)')
    ap.add_argument('--skip-fetch', action='store_true', help='Usa i dati MT5 già scaricati (nessun fetch)')
    ap.add_argument('--dry-run',    action='store_true', help='Nessuna scrittura su disco')
    args = ap.parse_args()

    print(f"═══ Reactivation Check — {datetime.date.today()} ═══")
    results = check(skip_fetch=args.skip_fetch, dry_run=args.dry_run)
    append_report(results, dry_run=args.dry_run)
    print("═══ Reactivation Check completato ═══")


if __name__ == '__main__':
    main()
