# TradeFlow AI — Data Sources & Critical Rules

## Asset

- **XAU/USD** (`GOLD` su MT5 XM) — asset primario, tutto il sistema live.
- **US30** (`US30Cash` su MT5 XM — "Wall Street 30 Index Cash", digits 2, contract 1.0, vol_min/step 0.1) — **in fase di ricerca strategia dal 2026-09-03**. Solo dati storici per ora; nessun flusso live né bot.
  - Storico: `python scripts/fetch_mt5_history.py --asset us30 --all-tf` → `data/us30_{tf}_mt5.json` (M15/M30/H1/H4/D1 = 2 anni pieni; M5 cap a 99999 bar ≈ 17 mesi). File **gitignored** (rigenerabili con MT5).
  - Spread US30Cash: ~1.5-3 pt in RTH, ~6 pt a mercato chiuso/weekend (vs XAU ~0.30).

## Fonte Dati Prezzi

- **Primaria**: TradingView Scanner (`scanner.tradingview.com/global/scan`)
- **Ticker XAU in ordine**: `OANDA:XAUUSD` → `FOREXCOM:XAUUSD` → `TVC:GOLD` (priorità deterministica in `lib/market-quotes.js`, indipendente dall'ordine della risposta).
- **Dashboard**: una sola richiesta batch `/api/market?type=prices` ogni 5 secondi per tutti i 13 simboli; un unico gruppo di card con prezzi nella valuta/unità dello strumento e variazione giornaliera. `/api/price` usa lo stesso normalizzatore. OIL usa `FX:USOIL`, fallback `TVC:USOIL`.
- Il timestamp indica la ricezione, non l'ora del tick del broker. Ritardi del provider possibili. Dati mancanti o guasti sono espliciti; gli ultimi prezzi restano marcati come tali, mai sostituiti da valori inventati.
- **MAI usare `GC=F`** per prezzi LIVE (Gold Futures COMEX ≠ spot — spread variabile)
- Nessun secondo feed Yahoo per le card live: prezzo e percentuale vengono dallo stesso snapshot TradingView. Qualunque futuro fallback Yahoo per XAU deve usare SOLO `XAUUSD=X` (spot), non `GC=F` o `GLD`.
- **Eccezione backtest**: `GC=F` via yfinance accettabile per backtest storico H1

## Fetch Candle per Indicatori

- **Vercel serverless IP sono blacklistati** da Yahoo Finance e `data.tradingview.com`
- **Strategy Engine (strategy.js)**: candele via `/api/price?type=candles` (proxy server-side)
- **MFKK (mfkk.js)**: candele direttamente da browser su `query1.finance.yahoo.com` (Chrome non è bloccato)
  - URL: `https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD%3DX?interval=1h&range=60d`
  - Range `60d` garantisce 120+ candle per warmup CCI(50)+Stoch(50)
- **MACD e ADX**: TV Scanner da server Vercel

## Colonne TV Scanner (timeframe H1)

Formato: `NOMECOL|60`

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

## Parametri Indicatori MFKK

| Indicatore | Parametri | Note |
|---|---|---|
| **CCI_S** | CCI=50, Stoch=50, K=8, D=8, OB=75, OS=25 | Pine Script v4, source=close |
| **MACD** | fast=12, slow=26, signal=9, type=EMA | Pine Script v6 default |
| **ADX** | Per=10, Th=10 | Custom "ADX and DI for v4" — usa SMA(DX,len) **NON** Wilder RMA |

> ⚠️ **ADX custom**: usa `SMA(DX,len)` non `RMA`. I valori TV Scanner (Wilder RMA 14) divergeranno significativamente.

## Protocollo Integrazione Nuovi Indicatori TradingView

1. Identificare segnali di entry/exit (BUY/SELL) e filtri dal Pine Script
2. Tradurre in JS in `modules/se-signals.js` dentro `SE_STRATEGY_FNS` come `S0X_NOME`
3. Valutare se servono nuove colonne TV Scanner (aggiungere in `api/price.js`)
4. Aggiungere la funzione Python in `scripts/signals.py` e importarla in strategy-engine-v2.py
5. Backtest: `scripts/strategy-engine-v2.py --file data/xauusd_m30_mt5.json` — minimo 6 mesi dati
6. Aggiornare `directives/02_strategies.md` + `directives/07_self_learning_log.md`


## Audit 2026-09-18

Le letture del conto richiedono un operatore o un utente esplicitamente autorizzato in `system_readers`; i comandi restano riservati agli operatori. Identità del servizio separata. KB personale in Turso, routing MyFxBook dedicato, endpoint FX corretto. Vedi 11_audit_and_release.md.


## Registro strumenti (2026-09-24)

`public/instruments.json` è la fonte unica degli strumenti: `id`, `label`, `type` (metal/fx/index), `core`, `decimals`, `chart` (widget TradingView), `quotes` (ticker scanner TradingView in ordine di priorità), `yahoo` (candele/indicatori), `mfx` (nome nel community outlook MyFxBook), `mt5` (nomi broker), `ccy`.
- Server: `lib/instruments.js` → `lib/market-quotes.js` (QUOTE_SYMBOLS = registro + 8 macro), `api/price.js` (candele con decimali dello strumento: prima `toFixed(2)` arrotondava l'FX), `api/analysis.js` (indicatori), `api/myfxbook.js` (nome sentiment).
- Client: `modules/instruments.js` (core inline + registro completo via `instrumentsReady`), selettore "Altri…" nell'header, griglia "Forex e indici" sotto il pannello del sistema.
- Asset sconosciuto → 400 esplicito (prima candele/indicatori ricadevano in silenzio sui ticker XAU).
- Strumenti `core:false`: confidence e MFKK mostrano un avviso invece di punteggi calcolati con soglie dell'oro; `dashContext.confidence=null` per non passarlo all'AI.
- Ticker verificati il 2026-09-24: OANDA per i forex; per gli indici lo scanner non restituisce i CFD OANDA/FOREXCOM/PEPPERSTONE/CAPITALCOM → `SP:SPX`, `NASDAQ:NDX`, `OANDA:DE30EUR`/`TVC:DEU40`, `TVC:UKX`, `TVC:NI225`. Nomi MT5 XMGlobal: `US500Cash`, `US100Cash`, `GER40Cash`, `UK100Cash`, `JP225Cash`, forex senza suffisso.
- I nomi MyFxBook degli indici (`SPX500`, `NAS100`, `GER30`, `UK100`, `JPN225`) non sono verificati: se il simbolo non c'è, il pannello lo dice invece di mostrare numeri.


## Scheda strumento ("memoria per coppia", 2026-09-24)

`scripts/instrument_profile.py` (eseguito dal worker: al primo avvio, poi se la cache ha più di 24h, e su richiesta col bottone "↻ Aggiorna" della scheda → job `kind='profile'`) calcola per ogni strumento del registro:
- **Contratto dal broker** (MT5 `symbol_info`): simbolo, cifre, contract size, lotto min/step, swap.
- **Costi reali**: spread mediano e p90 degli ultimi 30 giorni dalla colonna `spread` delle barre H1 MT5, e **costo/ATR H1**. Soglie: < 5% basso, 5-15% medio, > 15% alto (scalp sconsigliato). Primo calcolo (2026-09-24): XAU 2,3%, NAS100 2,8%, JP225 2,9%, GER40 3,3%, US500 4,4%, US30 4,5%, USDJPY 8,7%, UK100 8,9%, GBPUSD 10,5%, EURUSD 12,3%, XAG 15,8%, USDCHF 16,6%, AUDUSD 20,0%, USDCAD 27,3%, NZDUSD 27,8%.
- **Volatilità**: ATR(14) D1, range medio giornaliero % 90g, 3 ore broker con range H1 medio più ampio.
- **Correlazioni** dei rendimenti giornalieri (90 giorni e 1 anno, date comuni).
- **COT CFTC** (`publicreporting.cftc.gov`, legacy futures-only, non-commercial): netto, % open interest, variazione settimanale, segno invertito per USD/xxx (campo `cot` del registro). GER40/UK100 senza contratto CFTC; Nikkei CFTC fermo a marzo 2026 → escluso.
- **Ricerca già fatta**: somma trial e ultime note da `data/research_trials.json` per asset.
Pubblicata con `profiles_push` (doc `system/instrument_profiles`, circa 23 KB), letta dalla scheda in dashboard (`modules/instrument-card.js`). News: calendario esistente filtrato per le valute dello strumento (calendario esteso a CHF/CAD/NZD). Note personali: doc `inst_notes` sull'account.
Anche `_rates()` usa tentativi con controllo di completezza (simboli appena attivati: GBPUSD/USDJPY davano correlazioni sbagliate al primo giro).

**Fattore COT del confidence score: morto.** `loadCotData()` cerca `d.cot`, ma `type=cot` restituisce il file senza quella chiave, quindi `window._cotData` non viene mai valorizzato e il fattore resta sempre 50; il file `data/cot_data.json` era comunque un seed fermo a marzo 2026. Non collegato ai dati CFTC reali senza conferma dell'utente (cambierebbe il punteggio).
