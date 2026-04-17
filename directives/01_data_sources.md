# TradeFlow AI — Data Sources & Critical Rules

## Fonte Dati Prezzi

- **Primaria**: TradingView Scanner (`scanner.tradingview.com/global/scan`)
- **Ticker XAU in ordine**: `OANDA:XAUUSD` → `FOREXCOM:XAUUSD` → `PEPPERSTONE:XAUUSD` → `TVC:GOLD` → `CAPITALCOM:GOLD`
- **MAI usare `GC=F`** per prezzi LIVE (Gold Futures COMEX ≠ spot — spread variabile)
- **Yahoo Finance come fallback SOLO con `XAUUSD=X`** (spot), non `GC=F` o `GLD`
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
