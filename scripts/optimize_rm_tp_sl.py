import sys, json, math
from backtest_mfkk_intraday import (load_json, compute, mfkk_score, INTRADAY_VARIANTS, 
                                    run_backtest_rm, calc_stats, stats_by_period)

def optimize_mfkk_score(c_h1, ind_h1):
    print("=== Ottimizzazione TP/SL MFKK Score (Risk Manager) ===")
    tp_range = [15.0, 18.0, 20.0, 22.0, 25.0, 30.0]
    sl_range = [8.0, 10.0, 12.0, 15.0, 18.0]
    best_pnl = -99999
    best_params = None
    best_stats = None

    for tp in tp_range:
        for sl in sl_range:
            trades = run_backtest_rm(c_h1, ind_h1, mfkk_score, base_tp=tp, base_sl=sl, session=(0,24))
            s = calc_stats(trades)
            if s and s['n'] > 50:
                print(f"TP={tp} SL={sl} -> PNL={s['pnl']} WR={s['wr']}% PF={s['pf']} MaxDD={s['dd']}")
                if s['pnl'] > best_pnl:
                    best_pnl = s['pnl']
                    best_params = (tp, sl)
                    best_stats = s
    return best_params, best_stats

def optimize_mfkk_intraday(c_h1, ind_h1):
    print("\n=== Ottimizzazione ATR TP/SL MFKK Intraday (Risk Manager) ===")
    vfn = INTRADAY_VARIANTS['V3_Sell_Exhaustion'] # Best variant
    tp_mults = [1.5, 2.0, 2.5, 3.0]
    sl_mults = [0.8, 1.0, 1.2, 1.5]
    best_pnl = -99999
    best_params = None
    best_stats = None

    for tp_m in tp_mults:
        for sl_m in sl_mults:
            # We must override the ATR mults in the backtest call.
            # run_backtest_rm expects base_tp and base_sl, but if use_atr=True, 
            # it uses internal hardcoded constants TP_ATR_MULT=2.0 and SL_ATR_MULT=1.0.
            # We need to hack or pass them if we update the function.
            # Since we can't easily pass them without changing the function, we'll patch it in memory.
            import backtest_mfkk_intraday
            backtest_mfkk_intraday.TP_ATR_MULT = tp_m
            backtest_mfkk_intraday.SL_ATR_MULT = sl_m
            trades = run_backtest_rm(c_h1, ind_h1, vfn, use_atr=True, session=(0,24))
            s = calc_stats(trades)
            if s and s['n'] > 20:
                print(f"TP_ATR={tp_m} SL_ATR={sl_m} -> PNL={s['pnl']} WR={s['wr']}% PF={s['pf']} MaxDD={s['dd']}")
                if s['pnl'] > best_pnl:
                    best_pnl = s['pnl']
                    best_params = (tp_m, sl_m)
                    best_stats = s
    return best_params, best_stats

if __name__ == '__main__':
    c_h1 = load_json('xauusd_h1_730d.json')
    ind_h1 = compute(c_h1)
    b_params_score, b_stats_score = optimize_mfkk_score(c_h1, ind_h1)
    b_params_intra, b_stats_intra = optimize_mfkk_intraday(c_h1, ind_h1)
    
    print("\n=== RISULTATI OTTIMIZZAZIONE ===")
    print(f"S00_MFKK_SCORE Best: TP={b_params_score[0]} SL={b_params_score[1]} -> PNL={b_stats_score['pnl']} DD={b_stats_score['dd']}")
    print(f"S05_MFKK_INTRADAY Best: ATR_TP={b_params_intra[0]} ATR_SL={b_params_intra[1]} -> PNL={b_stats_intra['pnl']} DD={b_stats_intra['dd']}")
