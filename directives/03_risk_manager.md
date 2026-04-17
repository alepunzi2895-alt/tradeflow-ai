# TradeFlow AI — Risk Manager (`risk_manager.py`)

## Logica AI Score → Tier

| Tier | AI Score | Lot Mult | TP Mult | SL Mult | BE trigger | TS Step |
|---|---|---|---|---|---|---|
| 🔵 CONSERVATIVE | < 40 | ×0.5 | ×1.0 | ×0.8 | 80% TP | 1.5×ATR |
| ⚪ NORMAL | 40-60 | ×0.8 | ×1.0 | ×1.0 | 70% TP | 1.5×ATR |
| 🟡 AGGRESSIVE | 60-75 | ×1.0 | ×1.5 | ×1.0 | 60% TP | 1.2×ATR |
| 🟠 STRONG | 75-85 | ×1.2 | ×1.8 | ×1.2 | 50% TP | 1.0×ATR |
| 🔴 MAX | > 85 | ×1.5 | ×2.0 | ×1.5 | 50% TP | 1.0×ATR |

## Flusso Operativo

1. **Ogni 60s**: fetch AI Score da Vercel DB (`/api/db?action=mt5_get`)
2. **Ad ogni segnale**: `RiskManager.get_order_params(ai_score, atr, strategy)` → lot/TP/SL/BE/TS
3. **Ad ogni barra**: `RiskManager.manage_positions()` gestisce posizioni aperte:
   - **Break Even**: sposta SL a entry+buffer quando raggiunge trigger %TP
   - **Trailing Stop**: attivato dopo BE, step = `ts_step × ATR` aggiornato ad ogni barra

## Parametri Base per Strategia (STRATEGY_BASE)

| Strategia | TP base | SL base | ATR-based |
|---|---|---|---|
| S05_MFKK_INTRADAY | ATR×2.0 | ATR×1.0 | Sì |
| S09_MFKK_SCALPING | ATR×3.0 | ATR×1.0 | Sì |
| S10_OB_FVG_SCALP | ATR×2.5 | ATR×1.2 | Sì |
| S16_GOLDEN_SQUEEZE | ATR×3.0 | ATR×1.2 | Sì · BE trigger +ATR×1.1 |
| S17_CONVERGENCE_SCALP | ATR×2.5 | ATR×0.8 | Sì |

## Esempio Log (score 78, tier STRONG)

```
🧠 AI Score aggiornato: 78.0 — tier: 🟠 STRONG
★ SEGNALE M30: BUY | Golden Squeeze V2 | Regime: TREND_UP
  | 🟠 STRONG manip=1.00 | lot=0.04 | TP=$50.0 | SL=$28.8
🛡️  BE ticket#12345: SL → 3238.74
📈 Trailing ticket#12345: SL → 3245.80
```

## Note Implementative

- `_pos_state` dict: traccia stato BE/TS per ogni ticket aperto. Cleanup automatico in `manage_positions()` confrontando i ticket aperti reali.
- Manipulation filter: se `ATR > manip_threshold × ATR_avg30`, `rp['paused'] = True` → skip ordine.
- Il bot fetchha AI Score da Vercel ogni 60s e aggiorna `current_ai_score` (global).
