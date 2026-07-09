"""
TradeFlow AI — Config Consistency Checker (deterministico, nessuna chiamata AI)
═══════════════════════════════════════════════════════════════════
Confronta staticamente (ast.parse + ast.literal_eval, MAI import/exec) le
tabelle parallele keyed per strategy_id che devono restare sincronizzate tra
più file. Previene la regressione del pattern di bug già visto due volte nel
progetto: STRATEGY_PARAMS/STRATEGY_ATR_PARAMS disallineate (2026-05-12) e
STRATEGY_OPTIMAL_TF/BASELINE_STATS disallineate (2026-07-09).

mt5-bot.py ha side-effect a import-time (rewrap di sys.stdout, FileHandler
su mt5-bot.log) oltre al trattino nel nome che rompe `import` diretto — per
questo (e per coerenza) tutti i file sono letti via AST, mai eseguiti.

Esclusi deliberatamente: performance_tracker.py::BACKTEST_BASELINES (wr/pf
aggiornati manualmente da osservazioni live recenti, diverge legittimamente
da BASELINE_STATS che è "backtest puro") e risk_manager.py::STRATEGY_BASE
(file legacy non usato). Confrontarli produrrebbe solo falsi positivi.

USO:
  python scripts/check_config_consistency.py
"""
import ast
import io
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SCRIPT_DIR)

CHECKS = [
    {
        'name': 'STRATEGY_OPTIMAL_TF vs BASELINE_STATS[tf] (daily_maintenance.py)',
        'file_a': 'scripts/daily_maintenance.py', 'var_a': 'STRATEGY_OPTIMAL_TF', 'field_a': None,
        'file_b': 'scripts/daily_maintenance.py', 'var_b': 'BASELINE_STATS',      'field_b': 'tf',
    },
    {
        'name': 'STRATEGY_PARAMS.sl_mult (mt5-bot.py) vs STRATEGY_ATR_PARAMS.sl_atr (risk_guardian.py)',
        'file_a': 'scripts/mt5-bot.py',       'var_a': 'STRATEGY_PARAMS',     'field_a': 'sl_mult',
        'file_b': 'scripts/risk_guardian.py', 'var_b': 'STRATEGY_ATR_PARAMS', 'field_b': 'sl_atr',
    },
    {
        'name': 'STRATEGY_PARAMS.tp_mult (mt5-bot.py) vs STRATEGY_ATR_PARAMS.tp_atr (risk_guardian.py)',
        'file_a': 'scripts/mt5-bot.py',       'var_a': 'STRATEGY_PARAMS',     'field_a': 'tp_mult',
        'file_b': 'scripts/risk_guardian.py', 'var_b': 'STRATEGY_ATR_PARAMS', 'field_b': 'tp_atr',
    },
]


class ExtractionError(Exception):
    pass


def _extract_dict_literal(filepath: str, var_name: str) -> dict:
    """
    Legge il file come testo, ast.parse, cerca l'Assign top-level a var_name
    e valuta il valore con ast.literal_eval. Non esegue MAI il file.
    Solleva ExtractionError su file mancante/parse fallito/var non trovata/
    valore non literal-evaluable — mai un mismatch silenzioso.
    """
    if not os.path.isfile(filepath):
        raise ExtractionError(f"file non trovato: {filepath}")
    try:
        with open(filepath, encoding='utf-8') as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)
    except (OSError, SyntaxError) as e:
        raise ExtractionError(f"parse fallito ({filepath}): {e}")

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if var_name in names:
            try:
                return ast.literal_eval(node.value)
            except (ValueError, SyntaxError) as e:
                raise ExtractionError(f"{var_name} in {filepath} non è un dict literal statico: {e}")

    raise ExtractionError(f"variabile {var_name} non trovata a top-level in {filepath}")


def _project(table: dict, field: str = None) -> dict:
    if field is None:
        return dict(table)
    return {sid: sub[field] for sid, sub in table.items() if isinstance(sub, dict) and field in sub}


def compare_tables(check: dict, root: str = None) -> tuple:
    """Ritorna (mismatches: list, errors: list) per un singolo check."""
    root = root or _ROOT_DIR
    try:
        table_a = _extract_dict_literal(os.path.join(root, check['file_a']), check['var_a'])
        table_b = _extract_dict_literal(os.path.join(root, check['file_b']), check['var_b'])
    except ExtractionError as e:
        return [], [{'check': check['name'], 'error': str(e)}]

    proj_a = _project(table_a, check.get('field_a'))
    proj_b = _project(table_b, check.get('field_b'))

    mismatches = []
    for sid in sorted(set(proj_a) | set(proj_b)):
        va = proj_a.get(sid, '<mancante>')
        vb = proj_b.get(sid, '<mancante>')
        if va != vb:
            mismatches.append({
                'check': check['name'],
                'strategy_id': sid,
                'a': f"{check['file_a']}::{check['var_a']}" + (f"[{check['field_a']}]" if check.get('field_a') else ''),
                'b': f"{check['file_b']}::{check['var_b']}" + (f"[{check['field_b']}]" if check.get('field_b') else ''),
                'value_a': va,
                'value_b': vb,
            })
    return mismatches, []


def check_all(root: str = None, files_filter: set = None) -> dict:
    """
    Esegue tutti i CHECKS (o solo quelli che toccano files_filter, usato da
    review_diff.py per restringere ai soli file monitorati dall'hook).
    Ritorna {'mismatches': [...], 'errors': [...]}. mismatches vuoto = tabelle sync.
    """
    out = {'mismatches': [], 'errors': []}
    for check in CHECKS:
        if files_filter is not None and check['file_a'] not in files_filter and check['file_b'] not in files_filter:
            continue
        m, e = compare_tables(check, root)
        out['mismatches'] += m
        out['errors'] += e
    return out


def format_mismatch(m: dict) -> str:
    return f"{m['check']} :: {m['strategy_id']}: {m['a']}={m['value_a']!r} vs {m['b']}={m['value_b']!r}"


def format_error(e: dict) -> str:
    return f"{e['check']}: {e['error']}"


def main():
    # UTF-8 stdout wrap solo qui (esecuzione standalone) — MAI a livello di modulo:
    # questo file viene importato da daily_maintenance.py/review_diff.py, che hanno
    # già fatto il proprio wrap; ri-wrappare a import-time chiude il buffer del
    # wrapper precedente al garbage collect ("I/O operation on closed file").
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    result = check_all()

    for e in result['errors']:
        print(f"[check_config_consistency] WARNING (fail-open): {format_error(e)}")

    if not result['mismatches']:
        print("[check_config_consistency] Nessun mismatch — tabelle sincronizzate.")
        sys.exit(0)

    print(f"[check_config_consistency] {len(result['mismatches'])} mismatch:")
    for m in result['mismatches']:
        print(f"  - {format_mismatch(m)}")
    sys.exit(1)


if __name__ == '__main__':
    main()
