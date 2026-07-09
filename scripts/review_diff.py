"""
TradeFlow AI — Pre-Commit Code Review (advisory, fail-open)
═══════════════════════════════════════════════════════════════════
Eseguibile sia come git hook (installato via install_git_hooks.py) sia
manualmente. Rivede il diff staged sui file più a rischio regressione del
progetto (scripts/signals.py, scripts/mt5-bot.py, scripts/risk_guardian.py)
cercando pattern di bug già visti in passato (vedi 07_self_learning_log.md).

Prima della chiamata AI, esegue anche un pre-check deterministico (no AI, no
costo) via scripts/check_config_consistency.py: se le tabelle di config tra
mt5-bot.py/risk_guardian.py sono già disallineate nello stato attuale, blocca
subito senza nemmeno chiamare l'API (è un fatto certo, non un'ipotesi).

Nessuna modifica automatica al codice — solo findings stampati a terminale.
Blocca il commit (exit 1) SOLO su finding di severità 'blocker'. Bypass
standard git sempre disponibile: `git commit --no-verify`.

Fail-open a più livelli: key mancante, timeout, errore rete/parsing, o
qualunque eccezione imprevista → warning stampato + exit 0. Un problema di
rete/API non deve mai poter bloccare un commit.

USO:
  python scripts/review_diff.py --staged            # uso normale (hook)
  python scripts/review_diff.py --base main          # confronto manuale con un ref
  python scripts/review_diff.py --staged --timeout 1 # test fail-open su timeout
"""
import sys
import io
import os
import subprocess
import argparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

MONITORED_FILES = [
    'scripts/signals.py',
    'scripts/mt5-bot.py',
    'scripts/risk_guardian.py',
]

KNOWN_BUG_PATTERNS = [
    "Funzioni duplicate con lo stesso nome nello stesso file: la seconda "
    "definizione sovrascrive silenziosamente la prima senza errore (es. def bb() "
    "duplicata in mt5-bot.py, 2026-04-23, BUG#4).",
    "`elif` invece di `if` tra blocchi indipendenti per timeframe: lega "
    "erroneamente l'esecuzione di un blocco (es. M30) alla condizione di un "
    "blocco precedente, bloccandolo per intero (2026-04-23, BUG#1).",
    "Parametri disallineati tra tabelle parallele che devono restare sincronizzate "
    "(es. STRATEGY_PARAMS in mt5-bot.py vs STRATEGY_ATR_PARAMS in "
    "risk_guardian.py — stesso campo, valori diversi per la stessa strategia, "
    "2026-05-12).",
    "Guard di sicurezza definita ma mai richiamata in un nuovo blocco segnale "
    "(es. has_position_in_direction() non chiamata in tutti i blocchi TF → "
    "doppia esposizione stessa direzione, 2026-05-12).",
    "Datetime tz-aware vs tz-naive: sottrazione tra datetime.now(UTC) e un "
    "datetime tz-naive da cache/fonte esterna → TypeError spesso catturato "
    "silenziosamente da un try/except esterno, disabilitando una feature senza "
    "errori visibili (2026-04-28, News Guardian).",
    "Commenti che driftano dal codice sottostante (es. doppia numerazione '4.' "
    "in risk_guardian.py, commenti su unità non ovvie tipo 'sl_usd è per "
    "0.01lot') — segnalali se il commento sembra descrivere logica diversa da "
    "quella effettiva.",
    "Nuovo blocco segnale/TF che omette i guard presenti nei blocchi analoghi "
    "(quality_gate(), has_position_in_direction(), news guardian, session "
    "filter) — 2026-07-07, quality_gate assente in M30/H4.",
    "Soglie di filtro (RSI/ADX/ecc.) impostate in modo da poter bloccare "
    "permanentemente un intero lato (buy o sell) in condizioni di mercato "
    "plausibili e prolungate (es. RSI>75 come gate in bull market strutturale, "
    "2026-07-07).",
]

DIFF_MAX_CHARS = 12000


def _repo_root() -> str:
    try:
        proc = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass
    return os.getcwd()


def get_diff(base_ref: str = None) -> str:
    """
    git diff --cached -- <MONITORED_FILES> (default)
    oppure git diff <base_ref> -- <MONITORED_FILES> se --base passato.
    Fail-open: '' su qualunque errore.
    """
    root = _repo_root()
    cmd = ['git', 'diff']
    if base_ref:
        cmd.append(base_ref)
    else:
        cmd.append('--cached')
    cmd += ['--', *MONITORED_FILES]

    try:
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=15)
        if proc.returncode != 0:
            return ''
        return proc.stdout
    except Exception:
        return ''


def build_review_prompt(diff_text: str) -> tuple:
    patterns_text = '\n'.join(f"{i+1}. {p}" for i, p in enumerate(KNOWN_BUG_PATTERNS))

    system = f"""Sei un senior code reviewer specializzato in bot di trading algoritmico Python (MetaTrader5) per XAU/USD. Rivedi ESCLUSIVAMENTE il diff fornito (formato `git diff`) sui file scripts/signals.py, scripts/mt5-bot.py, scripts/risk_guardian.py. Non hai accesso al resto del codebase: basa la review solo su quanto visibile nel diff.

Presta particolare attenzione a questi pattern di bug ricorrenti già visti in questo progetto:
{patterns_text}

Oltre a questi, segnala qualunque bug di correttezza generale evidente nel diff (logica invertita, off-by-one, eccezioni non gestite, side-effect su mt5.order_send senza guard, ecc.).

Rispondi SEMPRE con un singolo oggetto JSON valido, senza markdown fences:
{{
  "findings": [
    {{"severity": "blocker"|"warning"|"info", "file": "<path>", "area": "<funzione/area>", "description": "<1-2 frasi, italiano>"}}
  ]
}}
Usa "blocker" SOLO per bug che causerebbero comportamento sbagliato/pericoloso in produzione con alta confidenza (es. un pattern noto sopra, chiaramente riprodotto). "warning" per sospetti plausibili non certi. "info" per osservazioni minori. Se nessun problema: {{"findings": []}}."""

    truncated = diff_text
    if len(diff_text) > DIFF_MAX_CHARS:
        truncated = diff_text[:DIFF_MAX_CHARS] + '\n[diff troncato]'

    user = f"Rivedi questo diff:\n\n```diff\n{truncated}\n```"

    return system, user


def print_findings(findings: list):
    if not findings:
        print("[review_diff] Nessun problema rilevato.")
        return

    severity_order = {'blocker': 0, 'warning': 1, 'info': 2}
    severity_icon = {'blocker': '\U0001F534', 'warning': '\U0001F7E1', 'info': '\U0001F535'}
    ordered = sorted(findings, key=lambda f: severity_order.get(f.get('severity'), 3))

    print(f"\n[review_diff] {len(findings)} finding(s):\n")
    for f in ordered:
        icon = severity_icon.get(f.get('severity'), '⚪')
        sev = (f.get('severity') or '?').upper()
        print(f"  {icon} [{sev}] {f.get('file', '?')} :: {f.get('area', '?')}")
        print(f"      {f.get('description', '')}\n")


def main():
    ap = argparse.ArgumentParser(description='TradeFlow AI — Pre-Commit Code Review')
    ap.add_argument('--staged', action='store_true', default=True,
                     help='Rivedi il diff staged (default, usato dall\'hook)')
    ap.add_argument('--base', type=str, default=None,
                     help='Confronta con un ref invece dello staged (uso manuale)')
    ap.add_argument('--timeout', type=int, default=45,
                     help='Timeout HTTP in secondi (default 45 — misurato empiricamente: '
                          'adaptive thinking su questi prompt richiede tipicamente 20-45s)')
    args = ap.parse_args()

    diff_text = get_diff(args.base)
    if not diff_text.strip():
        print("[review_diff] Nessuna modifica ai file monitorati — skip.")
        sys.exit(0)

    # Pre-check deterministico (no AI, no costo): tabelle di config disallineate
    # sono un fatto certo, non un'ipotesi — se già presenti nello stato attuale
    # dei file monitorati, blocca subito senza nemmeno chiamare l'AI.
    try:
        import check_config_consistency
        cfg_result = check_config_consistency.check_all(files_filter=set(MONITORED_FILES))
    except Exception as e:
        print(f"[review_diff] WARNING: config consistency check fallito ({e}) — fail-open, si procede.")
        cfg_result = {'mismatches': [], 'errors': []}
    for err in cfg_result['errors']:
        print(f"[review_diff] WARNING (fail-open): {check_config_consistency.format_error(err)}")
    if cfg_result['mismatches']:
        print(f"[review_diff] {len(cfg_result['mismatches'])} mismatch di configurazione GIÀ PRESENTE "
              f"nello stato attuale dei file monitorati (fatto certo, non serve l'AI per confermarlo):")
        for m in cfg_result['mismatches']:
            print(f"  - {check_config_consistency.format_mismatch(m)}")
        print("[review_diff] Commit bloccato — API non chiamata (risparmio). Bypass: git commit --no-verify")
        sys.exit(1)

    try:
        import ai_review
    except ImportError as e:
        print(f"[review_diff] WARNING: modulo ai_review non disponibile ({e}) — fail-open, commit consentito.")
        sys.exit(0)

    if not ai_review.is_configured():
        print("[review_diff] WARNING: ANTHROPIC_API_KEY mancante — fail-open, commit consentito.")
        sys.exit(0)

    try:
        system, user = build_review_prompt(diff_text)
        parsed, err = ai_review.call_claude_json(
            system, user, max_tokens=4000, thinking='adaptive', timeout=args.timeout,
        )
    except Exception as e:
        print(f"[review_diff] WARNING: errore imprevisto ({e}) — fail-open, commit consentito.")
        sys.exit(0)

    if err:
        print(f"[review_diff] WARNING: AI review non disponibile ({err}) — fail-open, commit consentito.")
        sys.exit(0)

    findings = (parsed or {}).get('findings', []) if isinstance(parsed, dict) else []
    print_findings(findings)

    blockers = [f for f in findings if f.get('severity') == 'blocker']
    if blockers:
        print(f"[review_diff] {len(blockers)} BLOCKER — commit bloccato. "
              f"Bypass: git commit --no-verify")
        sys.exit(1)

    sys.exit(0)


if __name__ == '__main__':
    main()
