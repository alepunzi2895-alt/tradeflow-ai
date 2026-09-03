# TradeFlow AI — Bot MT5: Operazioni & Comandi

## Avvio Bot

```bash
# Prerequisiti: MT5 aperto + pip install MetaTrader5 python-dotenv
python -X utf8 scripts/mt5-bot.py              # live
python -X utf8 scripts/mt5-bot.py --dry-run    # simulazione (nessun ordine reale)

# Monitor log
Get-Content mt5-bot.log -Wait -Tail 20

# Kill processo zombie
taskkill /f /im python.exe
```

Output atteso all'avvio:
```
TradeFlow AI — MT5 Bot avviato
RiskGuardian attivo — equity iniziale=10000.00
StrategySelector attivo — selezione dinamica regime-based
Account: 990.81 EUR (equity=990.81, free margin=990.81)
```

## Flusso Loop Principale (ogni 1s)

```
atr_now = I_h1['atr'][i]
rg.manage_positions(mt5, SYMBOL, MAGIC, atr_now, current_regime)
  → BE + Trailing Stop + Early Exit + Regime Shift Override

fetch_remote_commands()     → comandi UI da Turso DB
sync_to_vercel()  (ogni 20s) → push stato account + posizioni + active_strategy

Su nuova candela H1 chiusa:
  compute_indicators()       → solo su nuova barra
  detect_regime()            → regime semplice (backward compat + logging)
  StrategySelector.select()  → regime esteso + scoring → best strategy + TF
  signal_fn()                → segnale (buy/sell) per la strategia selezionata
  rg.get_order_params()      → composite score → tier → lot/TP/SL/BE/TS params
  place_order()              → mt5.order_send()
  rg.register_position()     → avvia tracking lifecycle
```

## Due Agenti AI

### Strategy Selector (`strategy_selector.py`)

- Gira ogni barra H1 (non ogni tick)
- Input: indicatori H1, ora UTC (session)
- Output: `current_selector_result` → `selected_strategy`, `timeframe`, `confidence`, `reasoning`
- Fallback: se non disponibile, usa `get_signal()` con playbook statico

### Risk Guardian (`risk_guardian.py`)

- `get_order_params()`: chiamato ad ogni segnale valido
  - Input: `strategy_confidence` (da StrategySelector), `ai_score` (da Vercel), `atr`, condizioni account
  - Output: `lot`, `tp_usd`, `sl_usd`, `be_trigger`, `ts_step`, `tier_label`
- `manage_positions()`: chiamato ogni ciclo (~1s o 10s)
  - Gestisce: Break-Even, Trailing Stop, Early Exit, Regime Shift Override
- `register_position()`: chiamato dopo `place_order()` per inizializzare tracking ticket

## Sincronizzazione Vercel

Il `bot_status` pushato ogni 20s include ora:
```json
{
  "active_strategy": "S16_GOLDEN_SQUEEZE",
  "strategy_confidence": 0.85,
  "selector_reasoning": "Regime=TREND_DOWN (ADX=32, strength=0.85) | ..."
}
```

## Flusso Comando UI → MT5

```
1. Utente clicca "ESEGUI SU MT5" in strategy.js
2. POST /api/db action=mt5_command_push → salva in Turso DB
3. mt5-bot.py loop → fetch_pending_command() → legge comando ogni 5s
4. Verifica scadenza < 60s (age_s > 60 → ignorato)
5. place_order(direction, tp, sl, strategy) → mt5.order_send()
6. sync_to_vercel() → aggiorna UI
```

> **Latenza effettiva:** il polling è ogni 5s — un comando UI può richiedere fino a 10s
> (5s polling + CHECK_SEC=10s loop). Finestra di validità totale: 60s dall'invio.
> Se il bot non risponde entro 60s il comando scade silenziosamente.

## Retcode MT5 Comuni

| Retcode | Significato | Soluzione |
|---|---|---|
| **10027** | AutoTrading disabled | Abilitare Algo Trading in MT5 toolbar (▶ verde) |
| 10004 | Requote | Normale in volatilità alta — riprova al prossimo ciclo |
| 10006 | Request rejected | Broker rifiuta — verificare orari di trading |
| 10014 | Invalid volume | LOT_SIZE non valido — verificare dimensione minima |
| 10016 | Invalid stops | TP/SL troppo vicini — aumentare distanza |
| 10019 | No money | Margine insufficiente — ridurre LOT_SIZE |
| 10021 | No prices | Mercato chiuso o connessione assente |

## S30_DOW_DIP — US30, blocco isolato su 2° simbolo (2026-09-03 →)

Prima strategia su un asset diverso da XAU. Mean-reversion azionaria (Connors RSI(2), long-only, H4) — vedi `02_strategies.md`. **Completamente isolata** dal flusso XAU:

| aspetto | S30_DOW_DIP |
|---|---|
| Simbolo | `US30Cash` (risolto a startup da `US30_SYMBOL_CANDIDATES`; se non trovato → disattivata per la sessione) |
| Segnale | `signal_dow_dip()` da `signals.py`, valutato a ogni nuova barra H4 chiusa su `US30Cash` |
| Sizing | **lotto fisso** `US30_LOT`=0.10 (vol_min broker). NIENTE RiskGuardian / composite / compounding / StrategySelector. Fase small-size come fece S20 |
| SL/TP | hard, ATR-based: SL `US30_SL_ATR`=2.6×ATR, TP `US30_TP_ATR`=1.2×ATR — impostati sull'ordine, gestiti da MT5. Nessun trailing/BE (l'edge mean-rev dipende dal non trailare) |
| Time-stop | `_us30_manage()` chiude a mercato dopo `US30_MAX_BARS`=18 barre H4 (~72h) se non ha toccato TP/SL |
| Esposizione | max 1 posizione S30 · cooldown `US30_COOLDOWN_H`=4h tra ingressi · **non conta** in `MAX_OPEN_ORDERS` GOLD (simbolo diverso) · rispetta `news_paused` |
| Safety net | `is_hard_blocked('S30_DOW_DIP')` controllato prima di ogni ingresso — il self-learning può disattivarla (baseline WR 0.76 / PF 1.63 in `performance_tracker.BACKTEST_BASELINES`) |
| Stato | `data/us30_live_state.json` (ricostruito al riavvio da posizioni `US30Cash` col tag `S30`) |

**Per disattivare**: `US30_ENABLED = False` in `mt5-bot.py`. Le posizioni aperte restano gestite da MT5 (SL/TP). **Serve `US30Cash` visibile in Market Watch** sul terminal della VPS (il bot lo attiva via `symbol_select`, ma il terminal deve avere accesso al simbolo).

## S20_FIB_CONFLUENCE — integrata nel flusso normale (2026-09-01 →)

S20 (config di principio, OOS PF 1.72) girava dal 2026-08-28 **live sul bot ma isolata** a
lotto fisso 0.03. Dal **2026-09-01**, su richiesta esplicita (dopo solo 4gg di test isolato,
non i 4-6 settimane pianificati — deviazione consapevole dal piano originale), è stata
**promossa a strategia normale**:

| aspetto | S20 (ora) |
|---|---|
| Loop | blocco M5 dedicato in `mt5-bot.py::run()` (fondo loop) — resta fuori da `StrategySelector`/`STRATEGIES_CONFIG` (nessun supporto M5 nel selector H1/M30/H4), ma non più "isolata" nel senso di rischio/capitale |
| Sizing | **RiskGuardian** (`rg.get_order_params`): composite score/tier/compounding come le altre strategie, con **UNICA eccezione**: lotto finale ×`S20_LOT_MULT`=2.0. `strategy_confidence`=`S20_CONFIDENCE`=0.55 e `ai_score`=`S20_AI_SCORE_PROXY`=55.0 sono proxy fissi (nessun AI scorer nativo per il segnale M5) |
| Gestione posizione | mini-manager proprio invariato: SL strutturale + TP hard 2R; a TP1 (1R) chiude `S20_PARTIAL_LOT`=0.02 e sposta lo SL del residuo (0.01) a BE. `RiskGuardian.manage_positions` continua a saltarla (guardia `'S20' in comment`) — la lifecycle backtestata (OOS PF 1.72) dipende da questa gestione specifica, non generica |
| Esposizione | max 1 posizione S20 aperta · cooldown `S20_COOLDOWN_MIN`=120 min tra ingressi · rispetta ora anche `MAX_OPEN_ORDERS` condiviso e la guardia di correlazione direzionale (`has_position_in_direction`) |
| Cooldown SL condivisi | le chiusure S20 **ora contano** in `consecutive_sl_count` (globale) e `sl_cooldowns_until` (per-strategia) — rimossa la guardia `_is_s20_close`. Due SL consecutivi su S20 possono quindi mettere in pausa anche H1/M30 (cooldown globale) |
| Filtri rispettati | sessione 7–19 UTC, no lunedì, news pause (incl. riduzione lotto `news_risk_mult`), toggle auto-trade UI |
| Stato | `data/s20_live_state.json` (ricostruito al riavvio dalle posizioni aperte col tag `S20`, ora registrato anche in `_strategy_order_tickets` per il tracking chiusure/cooldown) |

Config segnale in `signals.py::signal_fib_confluence` (V2): ingresso confermato (2 candele) +
higher-low/lower-high + EMA200 M5 + SL `min(low−0.15·ATR, entry−1.5·ATR)` + TP1 1R / TP2 2R.

**Per disattivare**: `S20_ENABLED = False` in `mt5-bot.py` (riga ~111). Le posizioni aperte
restano con SL/TP hard, il mini-manager smette di gestirle.

**Card nel tab Strategie**: badge speciale rimosso (non più "🧪 LIVE 0.03") — appare come le
altre card attive. Il bot continua a POSTare i trade S20 reali aggregati (`s20_push_stats` →
`/api/db` action `s20_paper_push`, singleton `user_data` user_id='s20-paper') ad ogni sync; il
frontend legge `s20_paper_get` ogni 60s (naming legacy "paper" nel plumbing, dati reali).

**Da monitorare**: essendo ora nel percorso critico dei cooldown condivisi, un cluster di SL
su S20 può ridurre la frequenza di trading anche di H1/M30. Se questo si rivela un problema,
valutare di reintrodurre un cooldown per-strategia dedicato invece del globale condiviso.

## Reactivation Check — ri-test mensile strategie bloccate (2026-09-01 →)

`scripts/reactivation_check.py` ri-testa a backtest (non a trade live — vedi motivazione in
`07_self_learning_log.md` 2026-09-01) le strategie elencate in `data/hard_blocks.json`
(attualmente S00_MFKK, S09_MFKK_SCALPING, S18_RANGE_REVERSAL) e
segnala se WR/PF sono tornati sopra soglia (WR ratio≥70% baseline **e** PF≥1.2). **Advisory-only**
— non riattiva mai nulla da solo, appende una riga a `07_self_learning_log.md`. Per sbloccare
davvero: rimuovere a mano la entry da `data/hard_blocks.json`, committare, pull + restart bot su VPS.

```bash
python scripts/reactivation_check.py                # fetch + backtest + check
python scripts/reactivation_check.py --skip-fetch    # usa dati MT5 già scaricati
python scripts/reactivation_check.py --dry-run       # nessuna scrittura
```

**Setup Task Scheduler (1° di ogni mese, non ancora registrato)**:
```
schtasks /create /tn "TradeFlowAI_ReactivationCheck" /tr "python -X utf8 C:\path\to\tradeflow-ai\scripts\reactivation_check.py" /sc monthly /d 1 /st 07:00 /f
```

## Checklist Pre-Deploy

- [ ] Variabili usate = variabili definite nel file (scope check)
- [ ] `onclick='fn(${JSON.stringify(obj)})'` — no apostrofi nei campi stringa
- [ ] Fetch server-side con timeout < 8s (limite Vercel)
- [ ] `git add <file-specifico>` — non `git add .` per evitare commit `.env`
- [ ] `git push origin main` → attendere ~60s → verificare URL produzione
