# TradeFlow AI — Directive Layer (DOE Framework)

> Questo documento è la **Directive Layer** del Framework DOE applicato al progetto TradeFlow AI.
> L'agente AI (Orchestration Layer) **deve leggere questo file per intero** prima di qualsiasi intervento.
> Dopo ogni correzione o nuova feature, aggiornare questo file aggiungendo la riga nel Self-Learning Log.

---

## 0. AUTOAPPRENDIMENTO — PROTOCOLLO OBBLIGATORIO

Ogni volta che l'agente AI interviene su questo progetto deve seguire questo ciclo:

```
LEGGI → DIAGNOSTICA → AGISCI → REGISTRA → MIGLIORA
```

### 0.1 Prima di ogni intervento
1. Leggere questo file intero.
2. Leggere il file coinvolto (MAI modificare codice non letto).
3. Cercare nel **§6 Self-Learning Log** se il bug è già noto.
4. Controllare le **§3 Regole Critiche** per evitare regressioni note.

### 0.2 Dopo ogni correzione
1. Aggiungere riga nel **§6 Self-Learning Log** con: data, bug, causa radice, fix.
2. Se è un pattern ricorrente, aggiungere una regola in **§3**.
3. Se cambia l'architettura, aggiornare **§2**.
4. Se cambia il comportamento del bot, aggiornare **§11**.

### 0.3 Regole di autodiagnosi
- **Se un componente restituisce `undefined` o `ReferenceError`**: cercare dove la variabile è definita e verificare scope e naming.
- **Se un ordine MT5 fallisce con retcode**: cercare il codice nella tabella **§10.4** prima di modificare il codice.
- **Se un'API restituisce dati errati**: verificare se il problema è lato Vercel (IP blacklist) o lato browser prima di cambiare la sorgente dati.
- **Se la UI non si aggiorna**: ricordare che `seRefresh` ricostruisce l'intero `innerHTML` ogni **1 secondo** — le modifiche DOM asincrone su elementi dentro `#se-content` vengono sovrascritte.
- **Se un segnale MFKK_HWR non appare mai**: verificare che `dashContext.mfkk` esponga le chiavi `adx`, `dip`, `dim`, `macd`. La fallback `seInds.adx=25` è sempre < 35 → il segnale viene filtrato silenziosamente.
- **Prima di aggiungere una nuova strategia**: definire ID (`S01_*`, `S02_*`, …), scrivere la funzione in `SE_STRATEGY_FNS`, aggiungere entry in `SE.strategies` con stats backtest, inserire l'ID nella `regimePriority` corretta. MAI mettere in produzione senza backtest >= 6 mesi H1.

### 0.4 Protocollo integrazione nuovi indicatori TradingView
Quando l'utente fornisce un indicatore Pine Script da TradingView:
1. **Capire la logica**: identificare i segnali di entry/exit (BUY/SELL) e i filtri.
2. **Tradurre in JS**: riscrivere il calcolo in `strategy.js` dentro `SE_STRATEGY_FNS` come `S0X_NOMEIND`.
3. **Dati necessari**: valutare se l'indicatore richiede nuove colonne TV Scanner (aggiungere in `api/price.js`) o nuovi calcoli browser-side (aggiungere in `seInds`).
4. **Backtest**: eseguire `scripts/strategy-engine-v2.py` con il nuovo segnale su 730gg GC=F H1 prima di attivare in produzione.
5. **Aggiornare la directive**: aggiungere entry in §5.2, §5.3, §6 (Self-Learning Log), e §7 se la strategia ha parametri ottimizzati.

---

## 1. IDENTITÀ DEL PROGETTO

**TradeFlow AI** è una Progressive Web App (PWA) mobile-first per trader XAU/USD (oro spot).

| Attributo | Valore |
|---|---|
| **URL produzione** | https://tradeflow-ai-delta.vercel.app/ |
| **Repository** | https://github.com/alepunzi2895-alt/tradeflow-ai |
| **Deploy** | Vercel (auto-deploy su push a `main`) |
| **Stack frontend** | HTML/CSS/JS vanilla, no framework |
| **Stack backend** | Node.js serverless (Vercel Functions) |
| **DB** | Turso (libSQL) — credenziali in env Vercel |
| **Bot trading** | Python locale (`scripts/mt5-bot.py`) → MetaTrader 5 |
| **Workflow deploy** | modifica locale → `git push origin main` → Vercel (~60s) |

---

## 2. ARCHITETTURA DEL SISTEMA

```
public/
  index.html          ← UI principale, CSS inline, struttura tab, script caricati in fondo
  app.js              ← init, tab routing, overlays, profilo utente
  modules/
    core.js           ← storage locale, fetchJSON, API helpers, dashContext globale
    dashboard.js      ← prezzi live, AI Confidence Score (10 fattori), sentiment, macro
    mfkk.js           ← MFKK Strategy Score (CCI_S, MACD, ADX · scoring e segnali)
    strategy.js       ← Strategy Engine: regime detection, segnali multi-strategia, render UI, bridge MT5
    chat.js           ← AI analysis via Claude API, upload immagini grafici
    journal.js        ← trade log, coaching AI, reports
    myfxbook.js       ← account sync MyFxBook
    kb.js             ← Knowledge Base, upload documenti, search
    analysis.js       ← (dentro public/modules) wrapper UI per analisi tecnica

api/
  price.js            ← endpoint prezzi live XAU/USD (TV Scanner multi-ticker) + proxy candele
  analysis.js         ← SUPER HUB: prezzi, indicatori MACD/ADX/CCI, calendario, sentiment, COT
  market.js           ← Hub secondario: fallback per alcuni tipi di dati macro
  db.js               ← Gateway universale Turso DB: auth, trades, mt5_push/get, comandi, KB
  report.js           ← Report AI giornaliero via LLM
  webhook.js          ← Ricezione trades e notifiche push

scripts/
  mt5-bot.py                  ← Bot trading Python: loop 1s, bridge MT5 ↔ Vercel DB
  fetch_mt5_history.py        ← Scarica GOLD H1 da MT5 → xauusd_h1_mt5.json (dati broker reali)
  strategy-engine-v2.py       ← Backtester Python (--file xauusd_h1_mt5.json per dati MT5 reali)
  strategy-mtf.py             ← MTF backtester: strategie × 3 TF
  backtest-mfkk.mjs           ← Backtester Node.js MFKK con config ottimale
  optimize-full.py            ← Ottimizzatore grid search 3 fasi
  analyze-entry-conditions.py ← Analisi empirica zone indicatori su 2 anni H1

directives/
  tradeflow_ai_directive.md   ← QUESTO FILE — leggere sempre prima di intervenire
```

### 2.1 Flusso dati globale

```
Browser (strategy.js)
  └─ seRefresh() ogni 1s:
       ├─ GET /api/price?type=candles → calcola indicatori H1 localmente
       ├─ legge dashContext.mfkk (da mfkk.js, già calcolato)
       ├─ rileva regime + segnali
       ├─ GET /api/db action=mt5_get → dati account reali MT5
       └─ seRender() → ricostruisce TUTTO #se-content (innerHTML)

mt5-bot.py (locale, PC utente)
  └─ loop ogni 1s:
       ├─ manage_positions() → Break Even + Trailing Stop
       ├─ fetch_remote_commands() → POST /api/db action=mt5_command_get
       ├─ get_candles() → H1 bars da MT5 locale
       ├─ sync_to_vercel() → POST /api/db action=mt5_push
       └─ su nuova candela H1 chiusa → analisi regime + segnale autonomo
```

---

## 3. REGOLE CRITICHE — SEMPRE RISPETTARE

### 3.1 Fonte Dati Prezzi
- **Primaria**: TradingView Scanner (`scanner.tradingview.com/global/scan`)
- **Ticker XAU da provare in ordine**: `OANDA:XAUUSD`, `FOREXCOM:XAUUSD`, `PEPPERSTONE:XAUUSD`, `TVC:GOLD`, `CAPITALCOM:GOLD`
- **MAI usare `GC=F`** per prezzi LIVE (Gold Futures COMEX ≠ spot — spread variabile)
- **Yahoo Finance come fallback SOLO con `XAUUSD=X`** (spot), non `GC=F` o `GLD`
- **Eccezione backtest**: `GC=F` via yfinance è accettabile per backtesting storico H1 (pattern identici)

### 3.2 Fetch Candle per Indicatori
- **Vercel serverless IP sono blacklistati** da Yahoo Finance e `data.tradingview.com`
- **Strategy Engine (strategy.js)**: candele via `/api/price?type=candles` (proxy server-side)
- **MFKK (mfkk.js)**: candele direttamente da browser su `query1.finance.yahoo.com` (Chrome non è bloccato)
  - URL: `https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD%3DX?interval=1h&range=60d`
  - Range `60d` garantisce 120+ candle per warmup CCI(50)+Stoch(50)
- **MACD e ADX**: TV Scanner da server Vercel (no candle storiche necessarie)

### 3.3 Colonne TV Scanner
Formato corretto per timeframe H1: `NOMECOL|60`

| Indicatore | Colonna corretta | Note |
|---|---|---|
| MACD line | `MACD.macd|60` | Default params 12,26,9 ✅ |
| MACD signal | `MACD.signal|60` | ✅ |
| MACD hist | `MACD.hist|60` | ✅ |
| ADX | `ADX|60` | **SENZA** `[period]` — parametro custom non supportato |
| DI+ | `plus_di|60` | ✅ |
| DI- | `minus_di|60` | ✅ |
| CCI | `CCI[50]|60` | Forma parameterizzata supportata |

> ⚠️ **BUG NOTO**: `ADX[10]|60` con periodo custom restituisce `null` → convertito a `0`. Usare sempre `ADX|60`.

### 3.4 Parametri Indicatori MFKK
| Indicatore | Parametri | Note |
|---|---|---|
| **CCI_S** | CCI=50, Stoch=50, K=8, D=8, OB=75, OS=25 | Pine Script v4, source=close |
| **MACD** | fast=12, slow=26, signal=9, type=EMA | Pine Script v6 default |
| **ADX** | Per=10, Th=10 | Custom "ADX and DI for v4" — usa SMA(DX,len) **NON** Wilder RMA |

> ⚠️ **ATTENZIONE ADX**: Il custom indicator usa `SMA(DX,len)` non `RMA`. I valori TV Scanner divergeranno.

### 3.5 Regole DOM e JavaScript (CRITICO)

> ⚠️ **ATTENZIONE SCOPE VARIABILI**: Usare sempre il nome della variabile effettivamente definita nel file.
> Bug ricorrente: usare `online` invece di `botOnline` (definita nella closure di `seRender`).

- **seRefresh ogni 1s**: `setInterval(seRefresh, 1000)` ricostruisce `#se-content` intero ogni secondo.
  - Modifiche DOM asincrone a elementi figli di `#se-content` vengono **sovrascritte entro 1s**.
  - Il toast `#se-toast` è appeso a `document.body` — sopravvive al refresh.
  - I riferimenti `btn` catturati via `event?.target` possono diventare **stale DOM nodes** dopo 1s.
- **onclick con JSON.stringify**: usare apici singoli nell'attributo HTML `onclick='...'`.
  - JSON.stringify NON escapa apostrofi `'`. Se il campo `why` contiene apostrofi italiani (es. `dall'ADX`), il `onclick` si rompe silenziosamente.
  - **Fix preventivo**: codificare con `encodeURIComponent` o usare attributi `data-*` + `addEventListener`.
- **`event` global**: disponibile solo in script non-module (`<script src="...">` senza `type="module"`). Strategy.js è caricato come script normale — `event?.target` funziona.

### 3.6 Vincoli Infrastruttura Vercel

| Risorsa | Limite free tier |
|---|---|
| Execution time | 10s max per function |
| RAM | 1024 MB |
| Cold start | ~500ms — timeout < 8s in tutte le fetch |
| IP | Blacklistato da Yahoo Finance, data.tradingview.com |

**Pattern obbligatorio per ogni fetch server-side**:
```javascript
async function fetchT(url, opts={}, ms=8000) {
  const ctrl = new AbortController();
  const tid = setTimeout(() => ctrl.abort(), ms);
  try { const r = await fetch(url, {...opts, signal: ctrl.signal}); clearTimeout(tid); return r; }
  catch(e) { clearTimeout(tid); throw e; }
}
```

---

## 4. FLUSSO DI AGGIORNAMENTO LIVE

```
Ogni 1 secondo (seRefresh in strategy.js):
  └─ GET /api/price?type=candles → calcolo indicatori H1 browser-side
  └─ dashContext.mfkk → MFKK score già calcolato
  └─ POST /api/db action=mt5_get → account data + posizioni reali
  └─ seRender() → rebuild completo #se-content

Ogni 5 secondi (recalcIndicators in mfkk.js):
  └─ Inietta live XAU price nell'ultima candle
  └─ Ricalcola CCI_S + EMA50 + ATR(14) + SwingH/L

Ogni 60 secondi (loadIndicatorCandles in mfkk.js):
  ├─ BROWSER: fetch Yahoo XAUUSD=X candles → CCI_S + EMA50 + ATR + swings
  └─ SERVER: TV Scanner → MACD.macd|60, MACD.signal|60, ADX|60, plus_di|60, minus_di|60

mt5-bot.py ogni 1 secondo:
  ├─ fetch_remote_commands() → preleva comandi dalla UI
  ├─ manage_positions() → BE/TS attivi
  ├─ sync_to_vercel() → push stato conto
  └─ su nuova candela H1: analisi autonoma + ordine se segnale
```

---

## 5. STRATEGY ENGINE — DETTAGLIO TECNICO

### 5.1 Regime Detection
```javascript
seDetectRegime(I, i):
  ADX >= 28 → TREND_UP (DI+>DI-) o TREND_DOWN (DI->DI+)
  ADX >= 20 → WEAK_UP o WEAK_DOWN
  ATR > 1.35x ATR30 → VOLATILE
  default → RANGE
```

### 5.2 Strategie Attive (backtest MT5 GOLD H1 · 730gg · aggiornato 2026-04-14)
| ID | Label | WR | PF | P&L 24m | Regimi |
|---|---|---|---|---|---|
| S00_MFKK | MFKK Score | 42% | 1.19 | +$3.260 | Tutti |
| S05_MFKK_INTRADAY | MFKK Intraday | 37% | 1.24 | +$4.794 | Tutti |

**Breakdown per periodo (backtest MT5 GOLD H1 730d):**

| Strategia | 1 Mese | 6 Mesi | 12 Mesi | 24 Mesi | MaxDD |
|---|---|---|---|---|---|
| MFKK Score | +$284 | +$1.600 | +$1.936 | +$3.260 | -$1.332 |
| MFKK Intraday | +$1.082 | +$1.830 | +$4.179 | +$4.794 | -$1.367 |

> **Nota**: MFKK HighWR rimossa — con dati MT5 reali produce solo 3 trade in 24m (PF 0.83). Le condizioni ADX≥35 + spread DI≥20 + MACD≥0.5 si verificano raramente su GOLD.

**Strategie ARCHIVIATE** (logica JS mantenuta, non mostrate in UI):
- S00_MFKK_HWR, S01_OBV_MACD, S02_OBV_SELL, S02_ULTIMATE_RSI, S03_MOMENTUM, S04_ICT_ORDERFLOW
- S04_BB_SQUEEZE: rimossa — PF 1.04 non sufficiente, MaxDD alto ($1.290)
- S09_VWAP_WPR: rimossa — troppo rara (8 trade/anno), difficile da integrare
- S06_ORDERBLOCK: rimossa — PF 1.09 con 234 trade/anno, efficienza bassa
- S12_WPR_KELTNER: rimossa — P&L negativo (-$246) su 2 anni
- S13_STRUC_BREAK: rimossa — P&L -$1.411 ❌
- S14_KEY_LEVELS: rimossa — P&L -$633 ❌
- S08_OBV_EMA_MOM: rimossa — P&L -$3.016 ❌

> **Prossimo step**: aggiungere strategie basate su indicatori TradingView personalizzati (Pine Script) → vedi §0.4 per il protocollo.

### 5.2 Strategie Archiviate (NON mostrate nell'UI, logica mantenuta nel codice)

Gli indicatori sviluppati in precedenza (Ultimate RSI, Momentum, ICT Order Flow, OBV MACD, OBV SELL, MFKK HighWR) sono stati mantenuti nelle loro funzioni JS ma **rimossi dalla UI** e dal catalogo `SE.strategies`. Possono essere riabilitati se il backtesting MT5 lo giustificasse.

### 5.3 Regime Priority (aggiornata 2026-04-14)
| Regime | Strategie priorità |
|---|---|
| TREND_UP | MFKK Score → MFKK Intraday |
| TREND_DOWN | MFKK Score → MFKK Intraday |
| WEAK_UP | MFKK Score → MFKK Intraday |
| WEAK_DOWN | MFKK Score → MFKK Intraday |
| RANGE | MFKK Intraday → MFKK Score |
| VOLATILE | MFKK Intraday → MFKK Score |

### 5.4 Parametri Operativi
- Max **10 trade/giorno**, cooldown **30 min** tra trade
- ATR filter: sospendi se ATR > 3.5x media 30 barre
- TP/SL: MFKK Score = $20/$12 fissi · MFKK Intraday = 2×ATR/1×ATR dinamici
- Sessione: 24h (MFKK Score e Intraday attivi tutto il giorno)

### 5.5 Procedura Backtest (Standard)
```bash
# Sempre usare --mt5 con MT5 aperto (dati broker reali GOLD)
python scripts/backtest_mfkk_intraday.py --mt5

# Fallback se MT5 non disponibile (dati storici salvati)
python scripts/backtest_mfkk_intraday.py --h1-file xauusd_h1_730d.json
```
> ⚠️ **Regola**: i risultati del backtest con `--mt5` sono la fonte di verità ufficiale. I valori nelle `stats` di `SE.strategies` devono sempre riflettere l'ultimo run MT5.

---

## 6. SELF-LEARNING LOG — BUG STORICI E FIX

> Aggiungere sempre una riga quando si risolve un bug. Questo evita di ripetere gli stessi errori.

| Data | Bug | Causa radice | Fix applicato |
|---|---|---|---|
| 2026-03-31 | Prezzi XAU non caricavano | Yahoo Finance bloccato + FPMARKETS ticker fallito | Multi-ticker TV Scanner (9 alternative) |
| 2026-03-31 | Indicatori MACD errati (+31 vs -12) | GC=F futures ≠ spot OANDA:XAUUSD | MAI usare GC=F per prezzi live; Yahoo XAUUSD=X come fallback |
| 2026-03-31 | "No candle data" su tutti indicatori | Vercel IP blacklistato da Yahoo Finance | Candele H1 fetched lato browser in mfkk.js |
| 2026-03-31 | ADX = 0,0,0 | `ADX[10]\|60` colonna non valida → null → 0 | Usa `ADX\|60` (default 14) sempre |
| 2026-03-31 | CCI_S mostra "auto" | `step="1"` rifiutava valori decimali | `step="0.01"` su input HTML |
| 2026-03-31 | ADX RMA vs SMA divergenza | Usavamo Wilder RMA, custom TV usa SMA(DX,len) | Server-side calcolo SMA(DX,10) |
| 2026-04-13 | `quality is not defined` | ReferenceError in dashboard.js:565 | Definito qualityBg/Col in updateConfidence() |
| 2026-04-13 | Duplicate strategy logic | strategy.js broken syntax | Unificata logica MT5/Signal, rimosso codice ridondante |
| 2026-04-13 | CORS Calendar Fail | Proxy 3rd party instabili | Creato /api/market server-side proxy per ForexFactory |
| 2026-04-13 | G/S Ratio e Oil bloccati | Ticker mancanti in API unificata | Aggiunti XAG (SILVER) e fallback OIL nel Hub |
| 2026-04-13 | Calendario non caricava | `nfs.faireconomy.media` offline + slice(0,15) basso | Multi-source fallback (3 URL FF), slice=60, mapping completo |
| 2026-04-13 | Grafico TradingView schiacciato | Height fissa 600px | Aumentata a 800px container HTML + widget JS |
| 2026-04-14 | MFKK non in sezione Strategies | SE non leggeva dashContext.mfkk | Aggiunti S00_MFKK (score≥75) e S00_MFKK_HWR |
| 2026-04-14 | Confirm dialog bloccava MT5 | `confirm()` bloccante | Rimosso confirm(), aggiunto toast `seToast()` non-bloccante |
| 2026-04-14 | Bottone MT5 sempre abilitato offline | Nessun check stato bot | `seSendTradeToMt5` verifica syncAge<30s prima di inviare |
| 2026-04-14 | Segnali MFKK troppo frequenti | Soglia 68 quasi sempre soddisfatta | Soglia alzata a 75; zona 80-89 ottimale (WR 58.8%) |
| 2026-04-14 | Catalog strategie senza P&L | Mostrava solo PF e WR | Aggiunte colonne P&L 1M/12M/24M e MaxDD |
| 2026-04-14 | Backtest XAUUSD=X delisted Yahoo | HTTP 404 su tutti i chunk | Migrato a GC=F via yfinance per backtesting storico |
| 2026-04-14 | S13/S14 in rotation con P&L negativo | Priority basata su stime | Rimossi dopo backtest 730gg; sostituiti con S04_BB_SQUEEZE in RANGE |
| 2026-04-14 | `ReferenceError: online is not defined` | Variabile `online` usata in seRender ma non definita; nome corretto è `botOnline` (definita alla riga 334) | Rinominato `online` → `botOnline` in strategy.js:367 |
| 2026-04-14 | Ordine MT5 fallisce `retcode=10027` | "AutoTrading disabled by client" — pulsante Algo Trading non attivo in MT5 | Non è un bug di codice — l'utente deve abilitare Algo Trading nella toolbar MT5 (vedi §10.4) |
| 2026-04-14 | S00_MFKK_HWR non scattava mai | `seInds.adx` è fallback statico (25) sempre < 35 → condizione ADX≥35 mai soddisfatta | Fix: S00_MFKK_HWR ora legge `dashContext.mfkk.adx/dip/dim/macd` reali, con fallback a seInds |
| 2026-04-14 | Architettura strategie semplificata | Decisione utente: tenere solo S00_MFKK e S00_MFKK_HWR · preparare slot per strategie TV | Rimosse S01/S04/S06/S09/S12/S13/S14 da SE.strategies, SE_STRATEGY_FNS, regimePriority |
| 2026-04-14 | mt5-bot.py aveva vecchie strategie (S01/S06/S09/S12) | STRATEGY_PARAMS e REGIME_PRIORITY non sincronizzati con strategy.js | Aggiornati in mt5-bot.py per usare solo S00_MFKK + S00_MFKK_HWR |
| 2026-04-14 | Backtester usava solo yfinance GC=F | Nessun modo per usare dati broker reali MT5 | Creato fetch_mt5_history.py + flag --file in strategy-engine-v2.py |
| 2026-04-14 | Integrazione Ultimate RSI, Momentum, ICT Order Flow | Utente ha richiesto 3 indicatori TV | Tradotti in JS (S02_ULTIMATE_RSI, S03_MOMENTUM, S04_ICT_ORDERFLOW) — logica mantenuta ma non mostrata in UI |
| 2026-04-14 | Refactoring UI Tab Strategie a 2 card | Utente richiede solo MFKK Score + MFKK Intraday · MFKK HighWR rimossa (3 trade in 24m PF 0.83 su dati MT5 reali) | Rimossi S01/S02/S03/S04/S00_MFKK_HWR da UI · S05_MFKK_INTRADAY = V2 Triple MACD H1 (WR 37% PF 1.24 24m $4.794) |
| 2026-04-14 | Backtest MT5 GOLD reale — M30 vs H1 verifica | V2 Triple MACD H1 Score=4.149 vs M30 Score=∼2.1 · H1 3.75x più profittevole | Confermato H1 come TF ottimale per MFKK Intraday |
| 2026-04-14 | UI Strategie: aggiunto trades/day per periodo | Richiesta utente: media trade giornalieri a 1/6/12/24 mesi | Aggiunti td_1m/td_6m/td_12m/td_24m in SE.strategies.stats · backtest_mfkk_intraday.py updated con avg_td nei periods |
| 2026-04-14 | Bot MT5 offline dopo crash silenzioso | Processo python.exe rimasto bloccato in background (zombie) impediva nuova connessione MT5 (1 connessione Python max) | Fix: `taskkill /f /im python.exe` prima di riavviare · aggiunta logica reconnect automatico in loop · mt5-bot.py aggiornato con `STRATEGY_PARAMS` a 2 strategie reali |
| 2026-04-14 | Sync Vercel mai aggiornato ("804m fa") | `VERCEL_URL` terminava con `/` → doppio slash in `/api/db` → HTTP 404 silenzioso | Rimosso slash finale da VERCEL_URL · `last_sync_time = -999` per sync immediato al primo ciclo |

---

## 7. BACKTESTING & SCORING MFKK — PARAMETRI DEFINITIVI

### 7.1 Dataset e Metodo
- **Dataset primario**: MT5 GOLD (XMGlobal-MT5 6) · 730 giorni H1/M30/H4 reali · conto demo #1301224666 · sempre `--mt5`
- **Dataset fallback**: `xauusd_h1_730d.json` (11.449 candele H1 GC=F yfinance) se MT5 non disponibile
- **Procedura**: `python scripts/backtest_mfkk_intraday.py --mt5` con MT5 aperto
- **Bot operativo**: `python scripts/mt5-bot.py` — richiede MT5 aperto su conto #1301224666 (XMGlobal-MT5 6)
- **Comando kill zombie**: `taskkill /f /im python.exe` prima di ogni riavvio bot

### 7.2 Parametri Scoring Ottimali (XAU)

| Parametro | Valore | Note |
|---|---|---|
| Peso CCI_S | 10% | ADX domina |
| Peso MACD | 10% | Secondario, conferma momentum |
| Peso ADX | 80% | Primario — trend e spread DI |
| Score entry BUY | ≥ 90 | WR 43.5% — richiede alta convinzione |
| Score entry SELL | ≥ 75 | WR 54.4% — soglia alzata da 68 a 75 |
| TP XAU | $20 (o 2x ATR) | Ottimizzato 730gg |
| SL XAU | $12 (o 1x ATR) | R:R 1.67:1 → PF 1.80 |
| EMA50 filter | OFF | Non bloccare trades |

### 7.3 HIGH-WR Signal (S00_MFKK_HWR) — Filtri Hard

Setup **SELL ONLY** con regole hard (no scoring):

| Filtro | Valore |
|---|---|
| ADX | ≥ 35 |
| DI spread | ≥ 20 (DI- > DI+) |
| MACD diff | ≥ 0.5 (MACD bullish esteso = segnale esaurimento) |
| CCI | ≥ 25 (non OS) |
| Sessione | London/NY (7-17 UTC) |

Risultati: N=28 su 730gg · **WR=92.9%** · PF=21.67 · MaxDD=-$12

### 7.4 Risultati Backtest Config Ottimale

| Metrica | MFKK | MFKK_HWR |
|---|---|---|
| Trades totali | 3.663 | 165 |
| Win Rate | 48.4% | **84.2%** |
| P&L 24m | **+$12.086** | +$2.443 |
| Profit Factor | 1.53 | **8.73** |
| Max Drawdown | -$1.220 | **-$61** |

### 7.5 Insights Chiave dal Backtest

1. **CCI è trend-continuation, NON mean-reversion** su H1 XAU:
   - CCI alto (OB ≥75) = uptrend in corso = entry BUY favorevole
   - La logica "compra oversold" è empiricamente sbagliata su questo TF/asset

2. **Pattern ESAURIMENTO (82-88% WR)**:
   - ADX≥35 + DI allineato + MACD in direzione OPPOSTA al trade
   - Il MACD "contro-trend" è il segnale più potente, non un filtro negativo

3. **Zona ottimale score 80-89** (WR 58.8%) — NON 90-100 (WR 48.2%):
   - Score estremi entrano troppo tardi quando il trend è già over-esteso

4. **SELL >> BUY su XAU H1**:
   - P&L SELL: $9.442 vs BUY: $2.643 su 2 anni

5. **EMA50 filter OFF** — il pattern di esaurimento SELL funziona anche sopra EMA50

---

## 8. AI CONFIDENCE SCORE (V2 — 10 FATTORI)

### 8.1 Pesi e Componenti (10% cadauno)

| Fattore | Tipo | Logica Score (Bullish XAU) |
|---|---|---|
| Momentum | Tecnica | Chg > 0.3% → Bullish |
| DXY Corr | Correlazione | DXY ↓ → Bullish XAU |
| Session KZ | Timing | London/NY Open → Bullish |
| Sentiment | Contrarian | Retail over-short (>65%) → Bullish |
| Multi-pair | Confluenza | EUR/GBP/XAU allineati → Bullish |
| US 10Y Yield | Macro | Rendimenti in calo → Bullish |
| G/S Ratio | Macro | Ratio in crescita → Safe Haven Bullish |
| COT Data | Smart Money | Istituzionali Net Long → Bullish |
| Volatilità | Rischio | ATR basso → setup puliti → Bullish |
| News Filter | Rischio | Nessuna news imminente (±30m) → Bullish |

### 8.2 Soglie Operative
- ≥ 75: FORTE BUY — Setup istituzionale confermato
- 60-74: BUY — Setup operabile
- 40-59: NEUTRO — Evitare entrate direzionali
- ≤ 25: FORTE SELL — Pressione ribassista coordinata

### 8.3 Adattamento XAU vs XAG
- **G/S Ratio per XAU**: Ratio alto (>78) = Safe Haven → Bullish Oro
- **G/S Ratio per XAG**: Ratio basso (<68) = Risk On → Bullish Argento

---

## 9. CHECKLIST PRE-DEPLOY

- [ ] Verificare che le variabili usate siano quelle effettivamente definite nel file (scope check)
- [ ] Verificare che `onclick='fn(${JSON.stringify(obj)})'` non contenga apostrofi nei campi stringa
- [ ] Fetch server-side con timeout < 8s (limite Vercel)
- [ ] `git add <file-specifico>` — non usare `git add .` per evitare commit accidentali di `.env` o file di log
- [ ] `git push origin main` → attendere ~60s per deploy Vercel
- [ ] Aprire https://tradeflow-ai-delta.vercel.app/ e verificare la sezione modificata

---

## 10. MT5 EXECUTION BRIDGE

### 10.1 Flusso Comando UI → MT5

```
1. Utente clicca "🚀 ESEGUI SU MT5" in strategy.js
2. seSendTradeToMt5(s) → verifica syncAge < 30s (bot online?)
3. POST /api/db action=mt5_command_push → salva in Turso DB
4. mt5-bot.py loop 1s → fetch_remote_commands() → legge comando
5. Verifica scadenza < 3 minuti (prevenzione esecuzione in ritardo)
6. place_order(direction, tp, sl, strategy) → mt5.order_send()
7. sync_to_vercel() → aggiorna UI con stato reale
```

### 10.2 Struttura Comando DB
```json
{
  "direction": "buy" | "sell",
  "strategy": "S00_MFKK",
  "tp": 20.0,
  "sl": 12.0,
  "symbol": "GOLD",
  "created_at": "2026-04-14T09:00:00Z"
}
```

### 10.3 Sicurezza
- Scadenza comandi: **3 minuti** dal `created_at`
- Secret condiviso: `MT5_BOT_SECRET` (env Vercel) ↔ `MT5_SECRET` (mt5-bot.py)
- Dry-run: `--dry-run` flag rispettato anche per comandi remoti
- Il bot non esegue ordini se c'è già una posizione aperta su GOLD

### 10.4 Retcode MT5 Comuni — Diagnosi

| Retcode | Significato | Soluzione |
|---|---|---|
| **10027** | AutoTrading disabled by client | Abilitare **Algo Trading** nella toolbar MT5 (icona ▶ deve essere verde) |
| 10004 | Requote | Normale in volatilità alta — il bot riproverà al prossimo ciclo |
| 10006 | Request rejected | Broker rifiuta — verificare orari di trading |
| 10014 | Invalid volume | LOT_SIZE non valido per il broker — verificare dimensione minima lotto |
| 10016 | Invalid stops | TP/SL troppo vicini al prezzo — aumentare distanza |
| 10019 | No money | Margine insufficiente — ridurre LOT_SIZE |
| 10021 | No prices | Prezzi non disponibili — mercato chiuso o connessione |

> ⚠️ **NOTA retcode 10027**: Non è un bug di codice. L'utente deve:
> 1. Aprire MT5 → toolbar in alto → pulsante **"Algo Trading"** → deve diventare **verde**
> 2. Tools → Options → Expert Advisors → **deselezionare** tutte le voci "Disabilita quando..."
> 3. Riavviare MT5 se il pulsante non risponde

### 10.5 Avvio Bot

```bash
# Prerequisiti: MT5 aperto + pip install MetaTrader5
cd scripts
python mt5-bot.py              # live
python mt5-bot.py --dry-run    # simulazione (nessun ordine reale)
```

Output atteso all'avvio:
```
TradeFlow AI — MT5 Bot avviato
✅ Simbolo Gold rilevato: GOLD
Account: 990.81 EUR (equity=990.81, free margin=990.81)
```

---

## 11. SISTEMA INTERATTIVO & EDUCATIONAL

### 11.1 Interactive Indicators
- Ogni indicatore nel dashboard è cliccabile → modal glassmorphism con spiegazione contestuale
- Logica in `dashboard.js` via `INDICATOR_DEFS`
- Spiegazioni cambiano in base al valore corrente dell'indicatore

### 11.2 Unified Market Hub (`api/analysis.js`)
- Singola fonte di verità per dati macro, calendario, sentiment, COT, indicatori
- **Resilienza**: timeout rigidi + fallback silenziosi (Yahoo Finance per Oil)
- Tipi supportati: `market`, `indicators`, `calendar`, `sentiment`, `cot`, `cot-update`

---

## 12. BACKLOG — PROSSIMI STEP

### Priorità Alta
- [ ] **Nuove strategie da indicatori TradingView** (Pine Script → JS) — prossimo step in sviluppo, vedi §0.4
- [ ] **Notifiche push** (Service Worker) quando Strategy Engine genera un segnale
- [ ] **Filtro news calendar**: skip 30 min prima/dopo high-impact events (già nel backlog da settimane)
- [ ] **Fix apostrofo in onclick**: sostituire `onclick='fn(${JSON.stringify(s)})'` con `data-signal` + `addEventListener` per evitare rottura silente su why fields in italiano

### Priorità Media
- [ ] Backtest periodico automatico (cron mensile) per rilevare drift parametri nel tempo
- [ ] Alert quando bot offline da > 5 minuti (notifica email o push)
- [ ] UI mobile: ottimizzare catalog strategie per schermi < 400px

### Priorità Bassa
- [ ] Fine tuning UI: animazioni transizione tra tab
- [ ] Export journal in CSV/PDF
- [ ] Integrazione COT data automatica settimanale

### Completati ✅
- [x] Strategy Engine con regime detection + segnali multi-strategia
- [x] MT5 Bridge bidirezionale (UI → bot → MT5)
- [x] Break Even e Trailing Stop automatici
- [x] Catalog strategie con statistiche P&L complete
- [x] MFKK HighWR signal (92.9% WR)
- [x] Report AI giornaliero (`api/report.js`)
- [x] Sync stato conto reale MT5 → UI in tempo reale
