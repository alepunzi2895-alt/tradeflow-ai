# TradeFlow AI — AI Review Agents

Due automazioni **advisory-only**: nessuna modifica automatica a codice o parametri, nessun agente nel path di esecuzione ordini reali. Entrambe usano `claude-sonnet-5` tramite un unico client condiviso, `scripts/ai_review.py`, e sono **fail-open** su qualunque problema (key mancante, timeout, errore rete/parsing) — non bloccano mai lo script di manutenzione né un commit per un problema di infrastruttura.

## `scripts/check_config_consistency.py` — pre-check deterministico (no AI, no costo)

Aggiunto 2026-07-09, gira **prima** sia in `daily_maintenance.py` che in `review_diff.py`. Confronta staticamente (via `ast`, mai import/exec — `mt5-bot.py` ha side-effect a import-time) tabelle parallele che devono restare sincronizzate: `STRATEGY_OPTIMAL_TF` vs `BASELINE_STATS[tf]`, `STRATEGY_PARAMS.sl_mult/tp_mult` vs `STRATEGY_ATR_PARAMS.sl_atr/tp_atr`. Se un mismatch è già presente nello stato attuale dei file monitorati, `review_diff.py` blocca il commit **senza chiamare l'AI** (fatto certo, non un'ipotesi — risparmio di tempo/costo). Esclude deliberatamente `BACKTEST_BASELINES`/`STRATEGY_BASE`, che divergono legittimamente da `BASELINE_STATS`. Uso standalone: `python scripts/check_config_consistency.py`.

## Setup one-time

1. **`ANTHROPIC_API_KEY` nel `.env` locale** — la chiave è già nota a Vercel (vedi `CLAUDE.md` → Environment Variables) ma finora era consumata solo lato JS (`api/chat.js`, `api/report.js`). Va replicata nel `.env` locale della VPS/macchina di sviluppo (stesso valore, chiave `ANTHROPIC_API_KEY=...`), altrimenti entrambe le feature restano in fail-open silenzioso (nessun errore bloccante, ma nessuna diagnosi/review).
2. **`pip install requests python-dotenv`** se l'ambiente non li ha già (sulla VPS dovrebbero essere già presenti, usati anche da `mt5-bot.py`).
3. **`python scripts/install_git_hooks.py`** — installa il pre-commit hook. Va rieseguito dopo ogni `git clone` fresco, perché `.git/hooks/` non è versionato da git.

## `scripts/ai_review.py` — client condiviso

Unico punto che parla con `api.anthropic.com`. **Regola: ogni chiamata Python a Claude passa da qui — mai `requests.post` diretto duplicato in altri script.**

- `call_claude(system, user, *, max_tokens=4000, thinking='adaptive', timeout=20, model='claude-sonnet-5')` — non solleva mai eccezioni, ritorna sempre `{'ok': True/False, ...}`.
- `call_claude_json(...)` — wrapper che valida/parsa la risposta come JSON.
- `is_configured()` — check rapido su `ANTHROPIC_API_KEY`, per evitare chiamate a vuoto.

`thinking` è sempre passato esplicitamente (`'adaptive'`, non omesso) e `max_tokens` ha margine abbondante — vedi `07_self_learning_log.md` (2026-07-09) per la lezione che ha motivato questa scelta: Sonnet 5 attiva adaptive thinking di default se `thinking` è omesso, e `max_tokens` è condiviso tra thinking e testo visibile, quindi un budget troppo stretto rischia una risposta vuota per troncamento silenzioso.

## Feature A — Root-Cause Diagnosis (`scripts/daily_maintenance.py`)

Estende la pipeline giornaliera esistente (drift analysis su backtest) con:

- **Trade Silence Check** (Step 4, `check_trade_silence()`): legge `mt5-trades.json` (root) e calcola i giorni dall'ultimo trade per ogni strategia attiva, confrontati con una soglia **per-strategia** (7-14gg a seconda della frequenza nativa del TF — vedi `STRATEGY_SILENCE_THRESHOLD_DAYS`). Questo è il check che il drift analysis basato su backtest non può fare: il bug del 2026-07-07 (`quality_gate` RSI>75 bloccava tutti i buy live) è rimasto invisibile 2,5 mesi perché quel gate esiste solo nell'esecuzione live, non nel backtester. Con questa soglia sarebbe stato flaggato entro la prima settimana.
- **AI Root-Cause Review** (Step 5, `run_ai_diagnosis()`): per ogni anomalia (drift PF/WR o silenzio trade), raccoglie contesto — sorgente della funzione `signal_*` pertinente (`scripts/signals.py`), righe storiche di `07_self_learning_log.md` per quella strategia, ultimi commit su `signals.py`/`mt5-bot.py` — e chiede a Claude un'ipotesi di causa (`root_cause`, `confidence`, `suspect_file`/`suspect_function`, `suggested_fix`). **Nessuna modifica di codice o parametri.**
- **Output**: nuove sezioni nel report giornaliero (`daily_report_<data>.txt`) + riga marcata `🤖 AI-Flagged <data>` in `06_known_issues.md` (Bug Aperti) — **non** in `07_self_learning_log.md`, riservato per convenzione ai fix confermati, non a ipotesi. Deduplicato per `(data, strategy_id)`: run ripetute lo stesso giorno non duplicano la riga.

Flag CLI: `--skip-ai-review` salta interamente lo Step 5 (zero chiamate API). `--dry-run` esegue comunque la diagnosi (visibile nel report a video) ma salta la scrittura su `known_issues.md`.

Zero chiamate API se non ci sono anomalie da diagnosticare in quel giorno.

## Feature B — Pre-Commit Code Review (`scripts/review_diff.py` + hook)

Alla `git commit`, se lo staged include `scripts/signals.py`, `scripts/mt5-bot.py`, `scripts/risk_guardian.py` o `scripts/performance_tracker.py` (aggiunto 2026-07-09 dopo il bug del comment troncato):

1. Legge `git diff --cached` limitato a quei 3 file. Se vuoto (nessuno dei 3 staged), exit 0 immediato — zero chiamate API, nessun check nemmeno sulla key.
2. Invia il diff a Claude con un system prompt che include `KNOWN_BUG_PATTERNS` (distillato da `07_self_learning_log.md`):
   - funzioni duplicate che si sovrascrivono silenziosamente
   - `elif` invece di `if` tra blocchi TF indipendenti
   - parametri disallineati tra tabelle parallele (es. `STRATEGY_PARAMS` vs `STRATEGY_ATR_PARAMS`)
   - guard di sicurezza definiti ma non richiamati in un nuovo blocco (es. `has_position_in_direction()`)
   - datetime tz-aware vs tz-naive
   - commenti che driftano dal codice sottostante
   - nuovo blocco segnale/TF che omette guard presenti nei blocchi analoghi
   - soglie di filtro che possono bloccare permanentemente un intero lato in condizioni di mercato plausibili
3. Stampa i findings a terminale (severità blocker/warning/info).
4. **Exit 1 solo se c'è almeno un finding "blocker"** → blocca il commit. Bypass standard: `git commit --no-verify`.

**Fail-open a più livelli**: key mancante, timeout (default 45s, misurato empiricamente — adaptive thinking su questi prompt richiede tipicamente 20-45s, configurabile con `--timeout`), qualunque eccezione imprevista → warning stampato, exit 0. Un problema di rete/API non blocca mai un commit.

Uso manuale (non solo come hook):
```
python scripts/review_diff.py --staged              # come l'hook
python scripts/review_diff.py --base main            # confronto con un ref
python scripts/review_diff.py --staged --timeout 1   # forza fail-open (test)
```

## Troubleshooting

| Sintomo | Causa probabile | Fix |
|---|---|---|
| Nessuna diagnosi/review, nessun errore visibile | `ANTHROPIC_API_KEY` mancante nel `.env` locale | Aggiungere la chiave (vedi Setup) |
| Hook non scatta al commit | `install_git_hooks.py` non rieseguito dopo un clone fresco | `python scripts/install_git_hooks.py` |
| Commit bloccato ma serve procedere comunque | Finding "blocker" plausibile ma falso positivo, o urgenza | `git commit --no-verify` |
| Falsi positivi ricorrenti sullo stesso pattern | Prompt troppo aggressivo su un caso specifico del codebase | Aggiustare `KNOWN_BUG_PATTERNS`/system prompt in `review_diff.py` — non costruire un allowlist automatico |
| Trade Silence flagga strategie appena aggiunte o a bassa frequenza | Soglia non ancora calibrata sui dati reali | Aggiustare `STRATEGY_SILENCE_THRESHOLD_DAYS` in `daily_maintenance.py` dopo qualche settimana di osservazione |
