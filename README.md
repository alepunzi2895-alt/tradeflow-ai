# TradeFlow AI

XAU/USD trading assistant with real-time TradingView prices.

## Structure
```
public/
  index.html         — shell (HTML only, no inline CSS/JS)
  styles.css         — all styles
  app.js             — init, tabs, overlays, profile, backup
  modules/
    core.js          — storage, API helpers, compression, context
    dashboard.js     — prices (TV Scanner + Yahoo), confidence score, sentiment, macro
    chat.js          — AI analysis, image upload, quick chips
    journal.js       — trade log, AI coaching, reports, memory
    myfxbook.js      — account sync, trade import
    kb.js            — knowledge base, GitHub sync
    mfkk.js          — MFKK strategy score, CCI/MACD/ADX indicators
api/
  chat.js            — Anthropic proxy
  market.js          — Yahoo Finance prices, sentiment, COT
  indicators.js      — OHLCV candles for indicator warmup
  price.js           — fast XAU price
  myfxbook.js        — MyFxBook API proxy
  kb.js              — GitHub knowledge base
  report.js          — AI coaching & reports
  webhook.js         — TradingView webhook receiver
  cot-update.js      — CFTC COT data fetcher
```

## Deploy
```bash
git init && git add . && git commit -m "init"
git remote add origin https://alepunzi2895-alt@github.com/alepunzi2895-alt/tradeflow-ai.git
git push origin main --force
```

## Env vars (Vercel)
- ANTHROPIC_API_KEY
- GITHUB_TOKEN (Contents: read+write)
- GITHUB_OWNER
- GITHUB_REPO
