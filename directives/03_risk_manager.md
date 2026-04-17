# TradeFlow AI — Risk Guardian Agent (`risk_guardian.py`)

> **Sostituisce** `risk_manager.py` come agente primario dal 2026-04-17.
> `risk_manager.py` è mantenuto come fallback per backward compat ma non viene usato direttamente.

## Composite Confidence Score

Il tier non è più basato solo sull'AI Score, ma su un composite pesato:

```
composite = strategy_confidence × 0.50
          + signal_quality      × 0.30   (AI Score / 100 come proxy)
          + market_conditions   × 0.20   (ATR stability + session liquidity + ADX)
```

`market_conditions = 0` → ordine sospeso (spike ATR > 2.5× avg).

## Tier di Rischio

| Tier | Score | Lot Mult | TP Mult | SL Mult | BE trigger | TS Step | Early Exit |
|---|---|---|---|---|---|---|---|
| 🔵 CONSERVATIVE | < 40 | ×0.5 | ×1.0 | ×0.8 | 80% TP | 1.5×ATR | 30% profit |
| ⚪ NORMAL | 40-60 | ×0.8 | ×1.0 | ×1.0 | 70% TP | 1.5×ATR | 20% profit |
| 🟡 AGGRESSIVE | 60-75 | ×1.0 | ×1.5 | ×1.0 | 60% TP | 1.2×ATR | 10% profit |
| 🟠 STRONG | 75-85 | ×1.2 | ×1.8 | ×1.2 | 50% TP | 1.0×ATR | 5% profit |
| 🔴 MAX | > 85 | ×1.5 | ×2.0 | ×1.5 | 50% TP | 1.0×ATR | 5% profit |

### Aggiustamenti Account Health

| Condizione | Effetto score |
|---|---|
| `today_pnl < -200` | −10 pt |
| `weekly_dd_pct > 3%` | −15 pt |
| `equity > initial × 1.05` AND `weekly_dd < 2%` | +5 pt |

## Circuit Breaker

| Trigger | Azione |
|---|---|
| Daily loss > 3% equity | Halt trading |
| Weekly drawdown > 5% | Halt trading |
| 5 consecutive losses | Halt trading |

## Compounding

```python
lot = base_lot × tier.lot_multiplier × min(sqrt(equity / initial_equity), 3.0)
# Cap aggiuntivo: max 2% risk per trade
```

## Position Management (`manage_positions()` — ogni 10s)

1. **Break-Even**: quando profit ≥ `be_trigger` → SL a entry+0.02
2. **Trailing Stop**: dopo BE, quando profit ≥ `trailing_activation` (BE+10%) → trail di `ts_step` ATR
3. **Early Exit**: se BE attivo ma trade stalled oltre `1.5 × expected_duration` con profit < `early_exit_threshold`
4. **Regime Shift Override**: chiude posizione se il regime attuale è ostile alla strategia di entrata (solo se già a BE o in profitto)

### Durate Stimate per Strategia

| Strategia | TF | Durata attesa |
|---|---|---|
| S05_MFKK_INTRADAY | H1 | 180 min |
| S05_MFKK_INTRADAY | M30 | 90 min |
| S09_MFKK_SCALPING | M5 | 20 min |
| S16_GOLDEN_SQUEEZE | M30 | 90 min |
| S10_OB_FVG_SCALP | M30 | 60 min |
| S17_CONVERGENCE_SCALP | M15 | 30 min |
| S17_CONVERGENCE_SCALP | M5 | 15 min |

## Flusso Operativo

```
1. Ogni 60s: fetch AI Score da Vercel DB → aggiorna signal_quality
2. Ad ogni segnale:
   a. StrategySelector.select() → strategy_confidence
   b. rg.get_order_params(strategy_confidence, ai_score, atr, ...) → lot/TP/SL/BE/TS
   c. place_order() → rg.register_position(ticket, params, strategy_id, tf, regime)
3. Ogni 10s: rg.manage_positions(mt5, symbol, magic, atr, current_regime)
```

## Parametri ATR per Strategia (STRATEGY_ATR_PARAMS)

| Strategia | TP ATR mult | SL ATR mult |
|---|---|---|
| S05_MFKK_INTRADAY | 2.0 | 1.0 |
| S09_MFKK_SCALPING | 3.0 | 1.0 |
| S10_OB_FVG_SCALP | 2.5 | 1.2 |
| S16_GOLDEN_SQUEEZE | 3.0 | 1.2 |
| S17_CONVERGENCE_SCALP | 2.8 | 1.1 |

> I moltiplicatori tier (tp_mult, sl_mult) vengono applicati sopra i base ATR mult. Es.: AGGRESSIVE tier, S16: TP = ATR × 3.0 × 1.5 = ATR × 4.5.

## Esempio Log

```
🛡️ RiskGuardian [🟡 AGGRESSIVE] strat=S16_GOLDEN_SQUEEZE comp=68 (str=0.85/sig=0.72/mkt=0.90)
   | lot=0.05 | TP=$45.00 SL=$20.00 | BE@+$27.00 | TS step=$8.00
🛡️  BE ticket#12345: SL→3238.74 — Profit 27.5 ≥ BE trigger 27.0
📈 Trail ticket#12345: SL→3245.80 (+7.06)
⏱️  Early exit ticket#12346 — Stalled: 8% profit after 135min (expected 90min)
🔄 Regime exit ticket#12347 — Regime shift: TREND_UP → RANGING (hostile to S05_MFKK_INTRADAY)
```
