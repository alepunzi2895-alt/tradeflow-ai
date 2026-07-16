"""
TradeFlow AI — Setup one-time del pre-commit hook (code review AI)
═══════════════════════════════════════════════════════════════════
`.git/hooks/` non è versionato da git, quindi va installato manualmente una
volta per ogni clone del repository. Questo script scrive un piccolo wrapper
in .git/hooks/pre-commit che invoca scripts/review_diff.py --staged — la
logica vera resta in scripts/ (versionata).

USO (una tantum, dopo ogni git clone):
  python scripts/install_git_hooks.py
  python scripts/install_git_hooks.py --force   # sovrascrive un hook esistente
                                                   # non installato da questo script

Vedi directives/09_ai_review_agents.md per il dettaglio del pre-commit review.
"""
import sys
import os
import subprocess
import argparse

MARKER = '# tradeflow-ai:review_diff'

HOOK_CONTENT = (
    "#!/bin/sh\n"
    f"{MARKER} — installato da scripts/install_git_hooks.py\n"
    "# NON modificare a mano: rieseguire scripts/install_git_hooks.py per aggiornare.\n"
    "exec python scripts/review_diff.py --staged\n"
)


def _run(cmd, cwd=None):
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=10)
    if proc.returncode != 0:
        raise RuntimeError(f"comando fallito: {' '.join(cmd)}\n{proc.stderr}")
    return proc.stdout.strip()


def main():
    ap = argparse.ArgumentParser(description='TradeFlow AI — Install pre-commit hook')
    ap.add_argument('--force', action='store_true',
                     help='Sovrascrivi un pre-commit hook esistente non installato da questo script')
    args = ap.parse_args()

    try:
        root = _run(['git', 'rev-parse', '--show-toplevel'])
        hooks_dir_rel = _run(['git', 'rev-parse', '--git-path', 'hooks'], cwd=root)
    except Exception as e:
        print(f"ERRORE: impossibile individuare la repo git ({e})")
        sys.exit(1)

    hooks_dir = os.path.join(root, hooks_dir_rel) if not os.path.isabs(hooks_dir_rel) else hooks_dir_rel
    os.makedirs(hooks_dir, exist_ok=True)
    hook_path = os.path.join(hooks_dir, 'pre-commit')

    if os.path.exists(hook_path):
        with open(hook_path, 'r', encoding='utf-8', errors='replace') as f:
            existing = f.read()
        if MARKER not in existing and not args.force:
            print(
                f"ATTENZIONE: {hook_path} esiste già e non è stato installato da questo "
                f"script.\nUsa --force per sovrascrivere.\n\n--- contenuto attuale (primi 300 char) ---\n"
                f"{existing[:300]}"
            )
            sys.exit(1)

    with open(hook_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(HOOK_CONTENT)

    try:
        os.chmod(hook_path, 0o755)
    except Exception:
        pass  # no-op su Windows, necessario su Linux/Mac

    print(f"Hook installato: {hook_path}")
    print("Test: modifica scripts/signals.py, `git add`, poi `git commit -m test`")
    print("Bypass: `git commit --no-verify`")


if __name__ == '__main__':
    main()
