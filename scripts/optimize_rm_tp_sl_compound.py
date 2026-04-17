import sys, json, math
from backtest_mfkk_intraday import (load_json, compute, mfkk_score, INTRADAY_VARIANTS, 
                                    run_backtest, simulate_portfolio)

if __name__ == '__main__':
    # 1. Carica candele H1 (2 anni)
    candles = load_json('data/xauusd_h1_730d.json')
    ind = compute(candles)
    print(f"  Caricato {len(candles)} candele da xauusd_h1_730d.json")

    # 2. Corri i backtest con le configurazioni ottimali trovate
    # S00 MFKK Score: TP=20, SL=10 (vincitore grid search per PNL/DD ratio)
    trades_mfkk = run_backtest(candles, ind, mfkk_score, tp_mode='fixed', tp_val=20.0, sl_val=10.0)
    for t in trades_mfkk: t['sl_val'] = 10.0
    
    # S05 MFKK Intraday: V3 Sell Exhaustion ultra-chirurgico (RSI>65, ADX>=30)
    # Importante: run_backtest usa internamente le varianti di backtest_mfkk_intraday.py
    v3_fn = INTRADAY_VARIANTS['V3_Sell_Exhaustion']
    trades_s05 = run_backtest(candles, ind, v3_fn, tp_mode='atr', tp_val=1.5, sl_val=1.0)
    # Per il calcolo del lotto nel compound, stimiamo un SL medio di 12.0 per S05
    for t in trades_s05: t['sl_val'] = 12.0 

    # 3. Simulazione Compound al 0.3% (Magic Combo)
    RISK_PCT = 0.003 # 0.3% rischio per trade (ottimale per restare sotto 40% DD con alto profitto)
    
    eq_mfkk, pnl_mfkk, dd_mfkk, wr_mfkk, pf_mfkk = simulate_portfolio(trades_mfkk, 1000.0, RISK_PCT)
    print(f"S00_MFKK (Compound {RISK_PCT*100:.1f}%): EQ=${eq_mfkk:.0f} PNL=+${pnl_mfkk:.0f} DD={dd_mfkk:.1f}% WR={wr_mfkk:.1f}% PF={pf_mfkk:.2f}")

    eq_s05, pnl_s05, dd_s05, wr_s05, pf_s05 = simulate_portfolio(trades_s05, 1000.0, RISK_PCT)
    print(f"S05_MFKK (Compound {RISK_PCT*100:.1f}%): EQ=${eq_s05:.0f} PNL=+${pnl_s05:.0f} DD={dd_s05:.1f}% WR={wr_s05:.1f}% PF={pf_s05:.2f}")

    all_trades = trades_mfkk + trades_s05
    all_trades.sort(key=lambda x: x['ts'])
    eq_all, pnl_all, dd_all, wr_all, pf_all = simulate_portfolio(all_trades, 1000.0, RISK_PCT)
    print(f"ALL_BOT (Compound {RISK_PCT*100:.1f}%): EQ=${eq_all:.0f} PNL=+${pnl_all:.0f} DD={dd_all:.1f}% WR={wr_all:.1f}% PF={pf_all:.2f}")
