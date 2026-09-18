#!/usr/bin/env python3
"""
scripts/obsidian_export.py — Export locale di TradeFlow AI verso un vault Obsidian
("secondo cervello").

Legge SOLO dati reali già esistenti:
  - Turso via /api/db (stesso pattern HTTP di daily_maintenance.py/mt5-bot.py — Vercel
    è read-only sul filesystem, quindi l'export gira come script locale, mai come api/*.js)
  - GitHub Contents API (data/knowledge.json, la stessa fonte di api/kb.js)
  - File locali del repo (directives/06_known_issues.md, directives/07_self_learning_log.md)

Scrive note Markdown con frontmatter YAML + [[wikilink]] in:
  Journal/     — una nota per trade (Turso, tabella trades)
  Genomi/      — una nota per strategia dall'ultimo report backtest (backtest_report_get);
                 lo score di "struttura dell'edge" replica gnScore() in
                 public/modules/backtest-report.js — tenere le due formule allineate se una
                 delle due cambia.
  Knowledge/   — le note della Knowledge Base (data/knowledge.json)
  AI-Log/      — righe delle tabelle in directives/06_known_issues.md e
                 directives/07_self_learning_log.md (diagnosi/fix storici)

Config (.env, SOLO locale — non va mai messo su Vercel):
  VERCEL_URL          default https://tradeflow-ai-delta.vercel.app (come gli altri script)
  OBSIDIAN_VAULT_PATH cartella del vault Obsidian su questo PC (richiesta)
  OBSIDIAN_USER_ID    user_id TradeFlow per leggere trades/user_data personali — trovalo
                       una volta sola da: DevTools browser → Application → Local Storage →
                       chiave "tf_profile" → campo "id" (oppure dal Network tab, body di una
                       qualsiasi chiamata POST /api/db dopo il login). Senza, l'export salta
                       solo Journal/ (Genomi/Knowledge/AI-Log non richiedono login).

Uso:
  python scripts/obsidian_export.py --dry-run     # stampa cosa scriverebbe, non tocca il vault
  python scripts/obsidian_export.py               # scrive/aggiorna le note nel vault
  python scripts/obsidian_export.py --only genomi # solo una sezione: journal|genomi|knowledge|ailog

Idempotente: ogni nota ha un nome file stabile (id/data+hash) — ri-eseguire sovrascrive la
stessa nota invece di duplicarla (stesso principio di dedup di
daily_maintenance.append_ai_findings_to_known_issues()).
"""
import argparse
import json
import math
import os
import re
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Console Windows in cp1252 di default -> crasha su emoji/frecce già presenti nelle
# directives (es. "→"). Stesso fix già usato in daily_maintenance.py per i subprocess.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import requests
except ImportError:
    print("Manca il modulo 'requests' — pip install requests", file=sys.stderr)
    sys.exit(1)

# .env generato da "vercel env pull" contiene spesso VERCEL_URL="" (vuoto, non assente) —
# os.getenv(...,default) non copre quel caso, serve "or" esplicito (stesso fix di mt5-bot.py).
VERCEL_URL = (os.getenv("VERCEL_URL") or "https://tradeflow-ai-delta.vercel.app").rstrip("/")
VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH")
USER_ID = os.getenv("OBSIDIAN_USER_ID")
REPO_ROOT = Path(__file__).resolve().parent.parent

BR_NAMES = {
    "S00_MFKK": "S00 · MFKK Score", "S09_MFKK_SCALPING": "S09 · MFKK Scalping",
    "S10_OB_FVG_SCALP": "S10 · OB+FVG Scalp", "S16_GOLDEN_SQUEEZE": "S16 · Golden Squeeze",
    "S17_CONVERGENCE_SCALP": "S17 · Convergence", "S18_RANGE_REVERSAL": "S18 · Range Reversal",
    "S20_FIB_CONFLUENCE": "S20 · Fib Confluence", "S31_LAYOUT_SMART": "S31 · Layout Smart",
    "S30_DOW_DIP": "S30 · Dow Dip (US30)",
}


# ── HTTP verso l'API già esistente (nessun nuovo endpoint) ──────────────────────
def db_call(action, timeout=15, **body):
    body["action"] = action
    r = requests.post(f"{VERCEL_URL}/api/db", json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ── Helper Markdown/vault ────────────────────────────────────────────────────
def slugify(text):
    text = re.sub(r'[\\/:*?"<>|]', "", text or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:150] or "nota"


def frontmatter(fields):
    lines = ["---"]
    for k, v in fields.items():
        if isinstance(v, list):
            items = ", ".join(json.dumps(x, ensure_ascii=False) if isinstance(x, str) else str(x) for x in v)
            lines.append(f"{k}: [{items}]")
        elif isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        elif v is None:
            lines.append(f"{k}:")
        elif isinstance(v, str):
            lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def write_note(subdir, filename, content, dry_run):
    rel = f"{subdir}/{slugify(filename)}.md"
    if dry_run:
        print(f"  [dry-run] {rel}  ({len(content)} char)")
        return
    path = Path(VAULT_PATH) / subdir / f"{slugify(filename)}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ── JOURNAL ───────────────────────────────────────────────────────────────────
def export_journal(dry_run):
    print("\n== Journal ==")
    if not USER_ID:
        print("  OBSIDIAN_USER_ID non impostato — salto (vedi docstring per come trovarlo).")
        return 0
    resp = db_call("get_trades", user_id=USER_ID, limit=2000)
    if not resp.get("ok"):
        print(f"  errore get_trades: {resp}")
        return 0
    trades = resp.get("trades", [])
    for t in trades:
        tid = str(t.get("id") or "")[:8]
        title = f"{t.get('trade_date','') or ''} {t.get('symbol','')} {t.get('direction','')} {tid}"
        strategy = (t.get("strategy") or "").strip()
        fm = frontmatter({
            "id": t.get("id"), "date": t.get("trade_date"), "symbol": t.get("symbol"),
            "direction": t.get("direction"), "result": t.get("result") or "",
            "pnl": t.get("pnl"), "source": t.get("source") or "manuale",
            "tags": ["journal", "trade"],
        })
        link = f"\n\nStrategia: [[Genoma {strategy}]]" if strategy else ""
        body = f"""{fm}

# {t.get('symbol','')} {t.get('direction','')} — {t.get('trade_date','') or ''}

- Entry: {t.get('entry_price','—')} · SL: {t.get('sl','—')} · TP1: {t.get('tp1','—')} · TP2: {t.get('tp2','—')}
- Risultato: **{t.get('result') or '—'}** · P&L: **{t.get('pnl','—')}**
- Emozione: {t.get('emotion') or '—'} · Errore: {t.get('mistake') or '—'}

{t.get('notes') or ''}
{link}
"""
        write_note("Journal", title, body, dry_run)
    print(f"  {len(trades)} trade esportati")
    return len(trades)


# ── GENOMI ────────────────────────────────────────────────────────────────────
# Stesso punteggio "struttura dell'edge" di gnScore() in
# public/modules/backtest-report.js — derivato solo da PF full/holdout + regime,
# NON è Sharpe/DSR accademico (non persistiti lato Python oggi).
def gn_score(info, regime):
    full = info.get("full") or {}
    holdout = info.get("holdout") or {}
    f_pf = full.get("pf") or 0
    h_pf = holdout.get("pf") or 0
    consistency = max(0.0, min(1.0, h_pf / f_pf)) if f_pf > 0 else 0.0
    durability = max(0.0, min(1.0, (h_pf - 1) / 1.5))
    coverage, regime_note = 0.5, "nessun dato di regime per questa strategia"
    observed = (regime or {}).get("observed") or {}
    if observed:
        ok_n = sum(1 for s in observed.values() if (s.get("pf") or 0) >= 1)
        coverage = ok_n / len(observed)
        regime_note = f"{ok_n}/{len(observed)} regimi osservati con PF>=1"
    n_trades = info.get("n_trades") or 0
    sample = max(0.0, min(1.0, math.log10(max(n_trades, 1) / 20) / math.log10(150 / 20))) if n_trades else 0.0
    score = round((consistency * 0.30 + durability * 0.30 + coverage * 0.25 + sample * 0.15) * 100)
    if score >= 70:
        tier = "TIER 1 · Credibile"
    elif score >= 45:
        tier = "TIER 2 · Da confermare"
    else:
        tier = "TIER 3 · Fragile"
    return dict(score=score, tier=tier, consistency=consistency, durability=durability,
                coverage=coverage, sample=sample, regime_note=regime_note)


def export_genomi(dry_run):
    print("\n== Genomi ==")
    resp = db_call("backtest_report_get")
    data = resp.get("data") if resp.get("ok") else None
    if not data:
        print("  nessun report backtest disponibile ancora (gira scripts/portfolio_backtest.py --push).")
        return 0
    pools = {**(data.get("shared_pool") or {}), **(data.get("isolated") or {})}
    regimes = data.get("regime_validation") or {}
    disabled = set(data.get("disabled") or [])
    synced_at = data.get("synced_at")
    n = 0
    for key, info in pools.items():
        s = gn_score(info, regimes.get(key))
        label = BR_NAMES.get(key, key)
        fm = frontmatter({
            "id": key, "tier": s["tier"], "score": s["score"], "tf": info.get("tf"),
            "n_trades": info.get("n_trades"), "disattivata": key in disabled,
            "aggiornato": synced_at, "tags": ["genoma", "strategia"],
        })
        body = f"""{fm}

# Genoma · {label}

**Score confidenza derivato: {s['score']}/100 · {s['tier']}**
(derivato da PF full/holdout + regime — non è Sharpe/DSR accademico, vedi nota nel codice)

- PF full: {(info.get('full') or {}).get('pf', '—')} · PF holdout: {(info.get('holdout') or {}).get('pf', '—')}
- Consistenza recente: {round(s['consistency']*100)}/100
- Durabilità: {round(s['durability']*100)}/100
- Copertura mercato: {round(s['coverage']*100)}/100 — {s['regime_note']}
- Ampiezza campione: {round(s['sample']*100)}/100 ({info.get('n_trades', 0)} trade)
{'- ⛔ **Disattivata** nel roster corrente' if key in disabled else ''}

Strategia: [[Strategia {key}]]
"""
        write_note("Genomi", f"Genoma {key}", body, dry_run)
        n += 1
    print(f"  {n} strategie esportate (sync {synced_at})")
    return n


# ── KNOWLEDGE ─────────────────────────────────────────────────────────────────
def export_knowledge(dry_run):
    print("\n== Knowledge ==")
    resp = db_call("kb_load")
    if not resp.get("ok"):
        print(f"  errore kb_load: {resp}")
        return 0
    items = resp.get("kb") or []
    for item in items:
        fm = frontmatter({"id": item.get("id"), "date": item.get("date"), "tags": ["knowledge"]})
        body = f"""{fm}

# {item.get('name', 'nota')}

{item.get('summary', '')}
"""
        write_note("Knowledge", item.get("name") or f"nota-{item.get('id')}", body, dry_run)
    print(f"  {len(items)} note esportate")
    return len(items)


# ── AI-LOG ────────────────────────────────────────────────────────────────────
def parse_md_table(path):
    """Ritorna le righe dati (liste di celle) di TUTTE le tabelle markdown nel file."""
    if not path.exists():
        return []
    rows, in_table = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if all(re.match(r"^:?-+:?$", c) for c in cells):
            in_table = True
            continue
        if in_table:
            rows.append(cells)
    return rows


def export_ailog(dry_run):
    print("\n== AI-Log ==")
    n = 0
    # cols = nomi colonna nell'ordine della tabella; title_idx = quale colonna usare come
    # titolo leggibile della nota (il testo del finding, non il path del file).
    sources = [
        ("06_known_issues.md", ["severity", "file", "issue"], 2),
        ("07_self_learning_log.md", ["data", "bug", "causa_radice", "fix"], 1),
        ("07_self_learning_auto.md", ["data", "bug", "causa_radice", "fix"], 1),  # gitignored, VPS-local — opzionale
    ]
    for fname, cols, title_idx in sources:
        path = REPO_ROOT / "directives" / fname
        rows = parse_md_table(path)
        for i, cells in enumerate(rows):
            date_m = re.search(r"\d{4}-\d{2}-\d{2}", cells[0])
            date = date_m.group(0) if date_m else ""
            raw = cells[title_idx] if title_idx < len(cells) else cells[0]
            title_raw = re.sub(r"[*_~`\[\]]", "", raw)
            title = title_raw[:90].strip() or f"riga {i}"
            fields = {c: (cells[j] if j < len(cells) else "") for j, c in enumerate(cols)}
            fm = frontmatter({"date": date, "source": fname, "tags": ["ai-log"]})
            body_rows = "\n\n".join(f"**{c}**\n\n{v}" for c, v in fields.items() if v)
            body = f"{fm}\n\n# {date} · {title}\n\n{body_rows}\n"
            write_note("AI-Log", f"{date} {i:02d} {title}", body, dry_run)
            n += 1
    print(f"  {n} note esportate (known_issues + self_learning_log)")
    return n


def main():
    ap = argparse.ArgumentParser(description="Export TradeFlow AI -> vault Obsidian")
    ap.add_argument("--dry-run", action="store_true", help="Stampa cosa scriverebbe, non tocca il vault")
    ap.add_argument("--only", choices=["journal", "genomi", "knowledge", "ailog"], help="Esporta solo una sezione")
    args = ap.parse_args()

    if not VAULT_PATH and not args.dry_run:
        print("OBSIDIAN_VAULT_PATH non impostato in .env — imposta il percorso del vault (o usa --dry-run).", file=sys.stderr)
        sys.exit(1)

    print(f"Vault: {VAULT_PATH or '(dry-run, nessun vault)'}")
    print(f"Vercel: {VERCEL_URL}")

    sections = {
        "journal": export_journal, "genomi": export_genomi,
        "knowledge": export_knowledge, "ailog": export_ailog,
    }
    todo = {args.only: sections[args.only]} if args.only else sections
    total = 0
    for name, fn in todo.items():
        total += fn(args.dry_run) or 0
    print(f"\nTotale note {'da scrivere' if args.dry_run else 'scritte'}: {total}")


if __name__ == "__main__":
    main()
