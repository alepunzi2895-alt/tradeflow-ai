"""Reproducible offline roster review. Never starts MT5, sends orders or promotes.

Existing datasets have been used in previous research: chronological holdout is
diagnostic, not fresh independent evidence. Eligibility below means paper candidate.
"""
import json, hashlib, subprocess, datetime, math
from pathlib import Path
import numpy as np
import portfolio_backtest as PB
import opt_harness as OH
from research_trials import record_trials

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'backtests'/'results'/'audit_2026-09-18'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def run():
    OUT.mkdir(parents=True,exist_ok=True)
    total=record_trials(9,asset='XAUUSD+US30',strategy_id='ROSTER_AUDIT',note='9 frozen baselines; no optimization; previously used history; chronological diagnostic only')
    all_results={**PB.run_shared_pool(),**PB.run_isolated()}
    report={'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'code_sha256':{str(p.relative_to(ROOT)):digest(p) for p in sorted((ROOT/'scripts').glob('*.py'))},
        'trial_count':total,'datasets':{},'strategies':{},
        'limitations':['Historical datasets already used in research; no unseen holdout claim.',
          'P&L in each simulator native units; do not sum XAU and US30 as account currency.',
          'Frozen standalone signals; live broker sizing/portfolio guard parity requires demo forward validation.',
          'Four chronological segments are stability diagnostics, not repeated fit/refit walk-forward.',
          'PBO requires a comparable candidate return matrix; not inferred from different-asset baselines.'],
        'live_promotions':[], 'execution_model':'causal-next-bar-stops-v1'}
    for sid,item in all_results.items():
        ev=item['ev'];tf=item['tf'];asset='us30' if sid.startswith('S30_') else 'xauusd'
        file=ROOT/'data'/f'{asset}_{tf.lower()}_mt5.json'
        raw=json.loads(file.read_text());candles=raw['candles'] if isinstance(raw,dict) else raw
        start,end=candles[0]['t'],candles[-1]['t'];cut=start+.8*(end-start)
        report['datasets'][file.name]={'sha256':digest(file),'count':len(candles),'first':start,'last':end}
        trades=ev['trades']
        def entry(t):
            return float(t.get('entry_ts') or datetime.datetime.fromisoformat(t['date']).replace(tzinfo=datetime.timezone.utc).timestamp())
        def exit_time(t):
            return float(t.get('exit_ts') or entry(t))
        # Exclude boundary-crossing trades. A seven-day gap is conservative for these frozen strategies.
        embargo=7*86400
        hold=[t for t in trades if entry(t)>=cut+embargo]
        folds=[]
        for k in range(4):
            lo=start+(cut-start)*k/4;hi=start+(cut-start)*(k+1)/4
            folds.append(OH.SE2.stats([t for t in trades if entry(t)>=lo+embargo and exit_time(t)<hi]))
        h=OH.SE2.stats(hold)
        daily={}
        for t in hold:
            date=datetime.datetime.fromtimestamp(exit_time(t),datetime.timezone.utc).date()
            daily[date]=daily.get(date,0)+t['pnl']
        dates=[];day=datetime.datetime.fromtimestamp(cut+embargo,datetime.timezone.utc).date()
        final=datetime.datetime.fromtimestamp(end,datetime.timezone.utc).date()
        while day<=final:
            if day.weekday()<5: dates.append(day)
            day+=datetime.timedelta(days=1)
        series=np.array([daily.get(day,0.) for day in dates],dtype=float)
        dsr=None
        if len(hold)>=30 and len(series)>=60 and series.std()>0:
            from scipy.stats import skew,kurtosis
            d=OH._load_overfit_detector().deflated_sharpe_ratio(observed_sr=OH.sharpe_from_pnl(series),num_trials=total,
                backtest_length=len(series),skewness=float(skew(series)),kurtosis=float(kurtosis(series,fisher=False)),annualization=np.sqrt(252))
            dsr={'pvalue':float(d.dsr_pvalue),'significant':bool(d.is_significant)}
        surcharge=3.0 if asset=='us30' else 1.0
        stress=OH.SE2.stats([{**t,'pnl':t['pnl']-surcharge} for t in hold])
        gates={'sample':h.get('n',0)>=30,'holdout_pf':h.get('pf',0)>=1.2,
            'holdout_positive':h.get('pnl',0)>0,'positive_segments':sum(f.get('pnl',0)>0 for f in folds)>=3,
            'extra_costs':stress.get('pf',0)>=1.0,'dsr':bool(dsr and dsr['significant'])}
        result={'tf':tf,'asset':asset,'full':ev['full'],'chronological_holdout':h,'cutoff':cut,'embargo_days':7,
            'segments':folds,'dsr':dsr,'extra_cost_per_trade_native_units':surcharge,'cost_stress':stress,
            'gates':gates,'paper_candidate':all(gates.values()),'live_approved':False,
            'native_holdout':ev['holdout'],'timestamp_coverage':sum(bool(t.get('entry_ts') and t.get('exit_ts')) for t in trades)}
        if result['timestamp_coverage'] != len(trades):
            result['gates']['complete_timestamps']=False;result['paper_candidate']=False
        report['strategies'][sid]=result
        (OUT/f'{sid}.json').write_text(json.dumps({'result':result,'trades':trades},indent=2,default=lambda v:v.item() if isinstance(v,np.generic) else str(v)),encoding='utf-8')
        print(sid, 'holdout',h,'gates',gates,flush=True)
    (OUT/'report.json').write_text(json.dumps(report,indent=2,default=lambda v:v.item() if isinstance(v,np.generic) else str(v)),encoding='utf-8')
    print('Saved',OUT/'report.json',flush=True)

if __name__=='__main__': run()
