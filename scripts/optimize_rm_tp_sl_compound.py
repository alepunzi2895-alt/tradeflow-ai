import sys, json, math
from backtest_mfkk_intraday import (load_json, compute, mfkk_score, INTRADAY_VARIANTS, 
                                    run_backtest_rm, calc_stats)

def simulate_portfolio(trades_list, initial_balance=1000.0, risk_pct=0.02, contract_size=100):
    equity = initial_balance
    peak_equity = equity
    max_dd_pct = 0.0
    compounded = []
    
    for t in sorted(trades_list, key=lambda x: x['ts']):
        sl_val = t.get('sl_val')
        if sl_val is None:
            # We must estimate sl distance. For S00 it is base_sl. Let's extract it or use an average.
            # Actually, `run_backtest_rm` doesn't currently output sl_val perfectly for calculation.
            # We'll use 10.0 and 1.0 * atr, let's just make it simple: 
            sl_val = 10.0
            
        risk_usd = equity * risk_pct
        dollar_risk_1_lot = sl_val * contract_size
        lot_size = risk_usd / dollar_risk_1_lot
        
        # Pnl in the trades dump is computed with fixed `base_lot`=0.02.
        # We need to scale it to `lot_size`
        original_lot = t['lot'] # this is base_lot * lot_mult
        # The base_lot was 0.02. So standard trade was using `original_lot`.
        # PNL = points * original_lot * 100
        points_gained = t['pnl'] / (original_lot * contract_size)
        
        real_pnl = points_gained * lot_size * contract_size
        equity += real_pnl
        if equity < 0:
            equity = 0; break
        if equity > peak_equity:
            peak_equity = equity
        dd_pct = (peak_equity - equity) / peak_equity * 100
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct
        compounded.append({'pnl': real_pnl, 'eq': equity})
        
    p_tot = equity - initial_balance
    wins = [x for x in compounded if x['pnl'] > 0]
    losses = [x for x in compounded if x['pnl'] < 0]
    wr = len(wins)/len(compounded)*100 if compounded else 0
    loss_sum = sum(abs(x['pnl']) for x in losses)
    pf = sum(x['pnl'] for x in wins)/loss_sum if loss_sum > 0 else 999
    
    return equity, p_tot, max_dd_pct, wr, pf

if __name__ == '__main__':
    c_h1 = load_json('xauusd_h1_730d.json')
    ind_h1 = compute(c_h1)
    
    # 1. Best per S00: TP=15, SL=8 (so it survives 1000$ starting balance)
    trades_s00 = run_backtest_rm(c_h1, ind_h1, mfkk_score, base_tp=15.0, base_sl=8.0, session=(0,24))
    for t in trades_s00: t['sl_val'] = 8.0
    
    import backtest_mfkk_intraday
    backtest_mfkk_intraday.TP_ATR_MULT = 1.5
    backtest_mfkk_intraday.SL_ATR_MULT = 1.0
    vfn = INTRADAY_VARIANTS['V3_Sell_Exhaustion']
    trades_s05 = run_backtest_rm(c_h1, ind_h1, vfn, use_atr=True, session=(0,24))
    # Approximation for SL distance
    for t in trades_s05: t['sl_val'] = 12.0 
    
    all_trades = trades_s00 + trades_s05
    
    # Simulate single S00 starting 1000
    eq0, p0, dd0, wr0, pf0 = simulate_portfolio(trades_s00, 1000.0, 0.005)
    print(f"S00_MFKK (Compound 0.5%): EQ=${eq0:.0f} PNL=+${p0:.0f} DD={dd0:.1f}% WR={wr0:.1f}% PF={pf0:.2f}")

    eq5, p5, dd5, wr5, pf5 = simulate_portfolio(trades_s05, 1000.0, 0.005)
    print(f"S05_MFKK (Compound 0.5%): EQ=${eq5:.0f} PNL=+${p5:.0f} DD={dd5:.1f}% WR={wr5:.1f}% PF={pf5:.2f}")

    eq_all, p_all, dd_all, wr_all, pf_all = simulate_portfolio(all_trades, 1000.0, 0.005)
    print(f"ALL_BOT (Compound 0.5%): EQ=${eq_all:.0f} PNL=+${p_all:.0f} DD={dd_all:.1f}% WR={wr_all:.1f}% PF={pf_all:.2f}")
