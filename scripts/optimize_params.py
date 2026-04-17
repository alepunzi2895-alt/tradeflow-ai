#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Parameter Optimization
Testa combinazioni sistematiche di parametri su tutti i backtest combinati.
Obiettivo: trovare la configurazione con WR 50-60% e P&L massimo.

USO:
  python scripts/optimize_params.py
  python scripts/optimize_params.py --phase 1   # solo TP/SL sweep
  python scripts/optimize_params.py --phase 2   # solo segnali sweep
  python scripts/optimize_params.py --phase all # tutto (default)
"""
import sys, io, json, math, datetime, argparse, bisect, itertools
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ap = argparse.ArgumentParser()
ap.add_argument('--h1',  default='data/xauusd_h1_mt5.json')
ap.add_argument('--m15', default='data/xauusd_m15_mt5.json')
ap.add_argument('--m30', default='data/xauusd_m30_mt5.json')
ap.add_argument('--phase', default='all', choices=['1','2','3','all'])
ap.add_argument('--out', default='optimize_results.json')
args = ap.parse_args()

try:
    from risk_manager import get_risk_manager
except ImportError:
    get_risk_manager = None

# ──────────────────────────────────────────────────────────────────────────────
# COPIA INFRASTRUTTURA da backtest_combined.py
# ──────────────────────────────────────────────────────────────────────────────
WARMUP_H1  = 250
MAX_LOOK   = 60
SESSION    = (7, 17)
MAX_TRADES_DAY = 3
EXTREME_K  = 3.0
H1_INTERVAL = 3600

def ema(src, p):
    k=2/(p+1); v=src[0]; o=[v]
    for x in src[1:]: v=x*k+v*(1-k); o.append(v)
    return o

def sma(src, p):
    o=[None]*(p-1)
    for i in range(p-1, len(src)):
        o.append(sum(src[i-p+1:i+1])/p)
    return o

def rsi14(src):
    p=14; n=len(src); out=[None]*n
    g=[max(0,src[i]-src[i-1]) for i in range(1,n)]
    lo=[max(0,src[i-1]-src[i]) for i in range(1,n)]
    if len(g)<p: return out
    ag=sum(g[:p])/p; al=sum(lo[:p])/p
    out[p]=100-100/(1+(ag/al if al>0 else 100))
    for i in range(p,len(g)):
        ag=(ag*(p-1)+g[i])/p; al=(al*(p-1)+lo[i])/p
        out[i+1]=100-100/(1+(ag/al if al>0 else 100))
    return out

def atr14(H, L, C):
    tr=[0]
    for i in range(1,len(C)):
        tr.append(max(H[i]-L[i], abs(H[i]-C[i-1]), abs(L[i]-C[i-1])))
    return sma(tr, 14)

def macd_calc(src):
    ef=ema(src,12); es=ema(src,26)
    ml=[ef[i]-es[i] for i in range(len(src))]
    ms=ema(ml,9)
    return ml, ms

def adx_wilder(H, L, C, p=14):
    n=len(C); adx=[None]*n; dip=[None]*n; dim=[None]*n
    if n<p+1: return adx, dip, dim
    tr=[0]; pdm=[0]; mdm=[0]
    for i in range(1,n):
        ht=H[i]-H[i-1]; lt=L[i-1]-L[i]
        tr.append(max(H[i]-L[i],abs(H[i]-C[i-1]),abs(L[i]-C[i-1])))
        pdm.append(max(ht,0) if ht>lt else 0)
        mdm.append(max(lt,0) if lt>ht else 0)
    atr_w=tr[:p+1]; pdi_w=pdm[:p+1]; mdi_w=mdm[:p+1]
    satr=sum(atr_w); spdi=sum(pdi_w); smdi=sum(mdi_w)
    for i in range(p,n):
        if i>p:
            satr=satr-satr/p+tr[i]
            spdi=spdi-spdi/p+pdm[i]
            smdi=smdi-smdi/p+mdm[i]
        pd_=100*spdi/satr if satr>0 else 0
        md_=100*smdi/satr if satr>0 else 0
        dip[i]=pd_; dim[i]=md_
        dx=100*abs(pd_-md_)/(pd_+md_) if (pd_+md_)>0 else 0
        if i==p:
            adx_val=dx
        else:
            adx_val=(adx[i-1]*(p-1)+dx)/p if adx[i-1] is not None else dx
        adx[i]=adx_val
    return adx, dip, dim

def mom10(src):
    out=[None]*10
    for i in range(10,len(src)): out.append(src[i]-src[i-10])
    return out

def obv_macd_tchannel(H, L, C, V):
    n=len(C); obv=[0]*n
    for i in range(1,n):
        if C[i]>C[i-1]: obv[i]=obv[i-1]+V[i]
        elif C[i]<C[i-1]: obv[i]=obv[i-1]-V[i]
        else: obv[i]=obv[i-1]
    e1=ema(obv,12); e2=ema(obv,26)
    mc=[e1[i]-e2[i] for i in range(n)]
    ms=ema(mc,9)
    out=[0]*n
    for i in range(n):
        if mc[i]>ms[i]: out[i]=1
        elif mc[i]<ms[i]: out[i]=-1
    return out

def calc_fvg(O, H, L, C):
    n=len(C); fb=[False]*n; fs=[False]*n
    for i in range(2,n):
        if L[i]>H[i-2]: fb[i]=True
        if H[i]<L[i-2]: fs[i]=True
    return fb, fs

def calc_order_blocks(O, H, L, C):
    n=len(C); ob=[False]*n; os_=[False]*n
    for i in range(3,n):
        if C[i-1]<O[i-1] and C[i]>H[i-1]: ob[i]=True
        if C[i-1]>O[i-1] and C[i]<L[i-1]: os_[i]=True
    return ob, os_

def cci50(H, L, C):
    n=len(C); out=[None]*49
    for i in range(49,n):
        tp=[(H[j]+L[j]+C[j])/3 for j in range(i-49,i+1)]
        mn=sum(tp)/50; md=sum(abs(x-mn) for x in tp)/50
        out.append((tp[-1]-mn)/(0.015*md) if md>0 else 0)
    return out

def compute_ind(candles):
    O=[c['o'] for c in candles]; H=[c['h'] for c in candles]
    L=[c['l'] for c in candles]; C=[c['c'] for c in candles]
    V=[c['v'] for c in candles]; n=len(C)
    I={'O':O,'H':H,'L':L,'C':C,'V':V,'n':n}
    I['e20']=ema(C,20); I['e50']=ema(C,50)
    I['e100']=ema(C,100); I['e200']=ema(C,200)
    I['rsi']=rsi14(C)
    I['atr']=atr14(H,L,C)
    I['atr30']=[None]*n
    for i in range(30,n):
        vals=[I['atr'][j] for j in range(i-30,i) if I['atr'][j] is not None]
        I['atr30'][i]=sum(vals)/len(vals) if vals else None
    I['adx'],I['dip'],I['dim']=adx_wilder(H,L,C,14)
    I['macd'],I['macd_sig']=macd_calc(C)
    I['mom']=mom10(C)
    I['cci']=cci50(H,L,C)
    try: I['obv_oc']=obv_macd_tchannel(H,L,C,V)
    except: I['obv_oc']=[0]*n
    try: I['fvg_bull'],I['fvg_bear']=calc_fvg(O,H,L,C)
    except: I['fvg_bull']=[False]*n; I['fvg_bear']=[False]*n
    try: I['ob_bull'],I['ob_bear']=calc_order_blocks(O,H,L,C)
    except: I['ob_bull']=[False]*n; I['ob_bear']=[False]*n
    return I

def regime(I, i):
    a=I['adx'][i]; dp=I['dip'][i]; dm=I['dim'][i]
    av=I['atr'][i]; aa=I['atr30'][i]
    if a is None: return 'UNKNOWN'
    if av and aa and av > EXTREME_K * aa: return 'EXTREME'
    if a >= 30: return 'TREND_UP' if dp>dm else 'TREND_DOWN'
    if a >= 22: return 'WEAK_UP'  if dp>dm else 'WEAK_DOWN'
    if av and aa and av > 1.4*aa: return 'VOLATILE'
    return 'RANGE'

def build_time_index(candles):
    return [c['t'] for c in candles]

def last_closed_idx(tf_times, h1_close_ts):
    pos = bisect.bisect_left(tf_times, h1_close_ts) - 1
    return pos

def simulate_ai_score(ind, i):
    a=ind['adx'][i]; r=ind['rsi'][i]; m=ind['macd'][i]
    atr=ind['atr'][i]; atr30=ind['atr30'][i]
    if None in (a, r, m): return 50.0
    score = 0.0
    score += min(max((a-20)/20,0),1.0)*30
    score += min(abs(r-50)/15,1.0)*20
    score += min(abs(m)/2.0,1.0)*20
    if atr and atr30:
        if a>=35:            score += 30
        elif a>=25:          score += 15
        elif atr>1.2*atr30:  score += 5
        else:                score += 10
    else: score += 10
    return round(min(max(score,0),100),1)

def load(path):
    try:
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
        candles = d.get('candles', d) if isinstance(d, dict) else d
        for c in candles:
            if 'o' not in c and 'open' in c:
                c['o']=c['open']; c['h']=c['high']; c['l']=c['low']
                c['c']=c['close']; c['t']=c['time']; c['v']=c.get('volume',1)
        return candles
    except Exception as e:
        print(f"  File non trovato: {path} ({e})")
        return []

# ──────────────────────────────────────────────────────────────────────────────
# FUNZIONI SEGNALE PARAMETRIZZATE
# ──────────────────────────────────────────────────────────────────────────────

def make_intraday(adx_min=20, rsi_bias=0, ema_filter=False, require_adx_vs_regime=False):
    """S05_MFKK_INTRADAY con parametri configurabili.
    adx_min: soglia ADX minima (20=current, 22, 25)
    rsi_bias: quanto RSI deve essere oltre 50 (0=current, 2, 5)
    ema_filter: richiede e20>e50 per buy, e20<e50 per sell
    """
    def fn(I, i):
        if i<2: return None
        oc=I.get('obv_oc', [])
        if not oc or i>=len(oc): return None
        r=I['rsi'][i]; mo=I['mom'][i]; a=I['adx'][i]; mc=I['macd'][i]
        if None in (r, mo, a, mc): return None
        if a < adx_min: return None
        if ema_filter:
            e20=I['e20'][i]; e50=I['e50'][i]
            if None in (e20, e50): return None
        rsi_buy_min  = 50 + rsi_bias
        rsi_sell_max = 50 - rsi_bias
        if oc[i] == 1 and r > rsi_buy_min and mo > 0 and mc > 0:
            if ema_filter and not (I['e20'][i] > I['e50'][i]): return None
            return 'buy'
        if oc[i] == -1 and r < rsi_sell_max and mo < 0 and mc < 0:
            if ema_filter and not (I['e20'][i] < I['e50'][i]): return None
            return 'sell'
        return None
    return fn

def make_sell_exhaust(rsi_min=60, adx_min=25, require_ema_bear=False):
    """S05_V3_Sell_Exhaust con parametri configurabili.
    rsi_min: RSI minimo per considerare overextension (60=current, 63, 65)
    adx_min: ADX minimo (25=current, 28, 30)
    require_ema_bear: richiede e20<e50 (bearish EMA alignment)
    """
    def fn(I, i):
        if i<1: return None
        oc=I['obv_oc']
        if i>=len(oc): return None
        r=I['rsi'][i]; a=I['adx'][i]; m=I['mom'][i]
        if None in (r,a,m): return None
        if require_ema_bear:
            e20=I['e20'][i]; e50=I['e50'][i]
            if None in (e20,e50) or e20>=e50: return None
        if oc[i]==-1 and r>rsi_min and a>=adx_min and m<0: return 'sell'
        return None
    return fn

def make_ob_fvg(adx_filter=0, require_trend=False):
    """S10_OB_FVG_SCALP con filtri aggiuntivi.
    adx_filter: ADX minimo (0=nessuno, 20, 22)
    require_trend: richiede EMA20>EMA50 per buy, <50 per sell
    """
    def fn(I, i):
        ob_b=I.get('ob_bull'); ob_s=I.get('ob_bear')
        fvg_b=I.get('fvg_bull'); fvg_s=I.get('fvg_bear')
        if ob_b is None or fvg_b is None: return None
        C=I['C']; O=I['O']
        bull_c = C[i] > O[i]
        bear_c = C[i] < O[i]
        if adx_filter > 0:
            a=I['adx'][i]
            if a is None or a < adx_filter: return None
        if require_trend:
            e20=I['e20'][i]; e50=I['e50'][i]
            if None in (e20,e50): return None
        if ob_b[i] and fvg_b[i] and bull_c:
            if require_trend and not (I['e20'][i] > I['e50'][i]): return None
            return 'buy'
        if ob_s[i] and fvg_s[i] and bear_c:
            if require_trend and not (I['e20'][i] < I['e50'][i]): return None
            return 'sell'
        return None
    return fn

def make_exhaustion(adx_min=25, spread_min=15, diff_min=0.7):
    """S01_EXHAUSTION con parametri configurabili."""
    def fn(I, i):
        a=I['adx'][i]; dp=I['dip'][i]; dm=I['dim'][i]
        ml=I['macd'][i]; ms=I['macd_sig'][i]
        if None in (a,dp,dm,ml,ms): return None
        diff=ml-ms; spread=abs(dp-dm)
        if a>=adx_min and dm>dp and spread>=spread_min and diff>=diff_min: return 'sell'
        if a>=adx_min and dp>dm and spread>=spread_min and diff<=-diff_min: return 'buy'
        return None
    return fn

def make_scalping(require_adx=False, adx_min=20):
    """S09_MFKK_SCALPING con filtri aggiuntivi."""
    def fn(I, i):
        e20=I['e20'][i]; e50=I['e50'][i]; e100=I['e100'][i]; e200=I['e200'][i]
        fb=I.get('fvg_bull'); fs=I.get('fvg_bear')
        if None in (e20,e50,e100,e200) or fb is None: return None
        if require_adx:
            a=I['adx'][i]
            if a is None or a < adx_min: return None
        if e20>e50>e100>e200 and fb[i]: return 'buy'
        if e20<e50<e100<e200 and fs[i]: return 'sell'
        return None
    return fn

def make_struc_break(lookback=30, retest_pct=0.002, adx_filter=0):
    """S13_STRUC_BREAK con parametri configurabili.
    lookback: barre per calcolare high/low (30=current, 40, 50)
    retest_pct: zona di retest in % (0.002=±0.2% current, 0.001=±0.1%)
    adx_filter: ADX minimo per il breakout (0=nessuno, 20, 25)
    """
    lb = lookback
    rp = retest_pct
    def fn(I, i):
        if i<lb+10: return None
        H=I['H']; L=I['L']; C=I['C']
        hh=max(H[i-lb:i]); ll=min(L[i-lb:i]); c=C[i]
        if adx_filter > 0:
            a=I['adx'][i]
            if a is None or a < adx_filter: return None
        if c>hh and L[i]<=hh*(1+rp) and L[i]>=hh*(1-rp): return 'buy'
        if c<ll and H[i]>=ll*(1-rp) and H[i]<=ll*(1+rp): return 'sell'
        return None
    return fn

def make_mfkk_score(bull_th=85, bear_th=70, adx_filter=0):
    """S00_MFKK con soglie configurabili."""
    def fn(I, i):
        if i<50: return None
        a=I['adx'][i]; dp=I['dip'][i]; dm=I['dim'][i]
        m=I['macd'][i]; c=I['cci'][i]
        if None in (a,dp,dm,m): return None
        if adx_filter > 0 and a < adx_filter: return None
        bull=bear=0.0
        ac=min(a/40*100,100)
        if dm>dp: bear+=ac*0.80
        else:     bull+=ac*0.80
        ms=min(abs(m)/0.5*100,100)
        if m>=0: bull+=ms*0.10
        else:    bear+=ms*0.10
        cs=min(abs(c or 0)/100*100,100)
        if (c or 0)>=0: bull+=cs*0.10
        else:           bear+=cs*0.10
        if bull>=bull_th: return 'buy'
        if bear>=bear_th: return 'sell'
        return None
    return fn

# ──────────────────────────────────────────────────────────────────────────────
# SIMULAZIONE CON PARAMETRI
# ──────────────────────────────────────────────────────────────────────────────

REGIME_MULTI_STRATEGIES = {
    'TREND_UP':   [('S05_V3_Sell_Exhaust','H1',None), ('S05_MFKK_INTRADAY','H1',None), ('S00_MFKK','H1','sell')],
    'TREND_DOWN': [('S01_EXHAUSTION','M15',None),     ('S05_MFKK_INTRADAY','H1',None), ('S00_MFKK','H1','buy')],
    'WEAK_UP':    [('S09_MFKK_SCALPING','H1',None),   ('S05_MFKK_INTRADAY','H1',None)],
    'WEAK_DOWN':  [('S09_MFKK_SCALPING','M30',None),  ('S05_MFKK_INTRADAY','H1',None)],
    'VOLATILE':   [('S09_MFKK_SCALPING','M30',None)],
    'RANGE':      [('S10_OB_FVG_SCALP','M30',None),   ('S13_STRUC_BREAK','H1',None)],
    'UNKNOWN':    [('S00_MFKK','H1',None)],
}

def run_sim(h1, m15, m30, ind_h1, ind_m15, ind_m30,
            times_m15, times_m30,
            signal_fns, tp_mult, sl_mult):
    """Esegue la simulazione con signal_fns e TP/SL moltiplicatori dati."""
    rm = get_risk_manager(base_lot=0.02, max_lot=0.10) if get_risk_manager else None
    trades = []
    equity_curve = []
    INITIAL_BALANCE = 1000.0
    equity = INITIAL_BALANCE
    open_trades = []
    MAX_OPEN_TRADES = 2
    cooldown_bars = 0
    trades_today = 0
    current_day = None

    for i in range(WARMUP_H1, len(h1)-1):
        h1_open_ts  = h1[i]['t']
        h1_close_ts = h1_open_ts + H1_INTERVAL
        bar_dt = datetime.datetime.fromtimestamp(h1_open_ts, tz=datetime.timezone.utc)
        hour   = bar_dt.hour

        day = bar_dt.date()
        if day != current_day:
            current_day  = day
            trades_today = 0

        # ── Gestione trades aperti ──────────────────────────────
        active_trades = []
        for trade_open in open_trades:
            tf  = trade_open['tf']
            hit = None
            if tf == 'H1':
                h=h1[i]['h']; l=h1[i]['l']
                if trade_open['dir']=='buy':
                    hit = 'sl' if l<=trade_open['sl'] else ('tp' if h>=trade_open['tp'] else None)
                else:
                    hit = 'sl' if h>=trade_open['sl'] else ('tp' if l<=trade_open['tp'] else None)
                if hit:
                    pnl_pts = trade_open['tp_pts'] if hit=='tp' else -trade_open['sl_pts']
                    pnl_usd = pnl_pts * trade_open['lot'] * 100
                    equity += pnl_usd
                    trade_open['result'] = hit; trade_open['pnl'] = pnl_usd
                    trade_open['close_t'] = h1_open_ts
                    trades.append(dict(trade_open))
                    equity_curve.append((h1_open_ts, equity))
                    cooldown_bars = 1
            else:
                tf_c = m15 if tf=='M15' else m30
                tf_t = times_m15 if tf=='M15' else times_m30
                j_end = last_closed_idx(tf_t, h1_close_ts)
                j_start = trade_open.get('last_checked_j', trade_open['open_bar_j'])+1
                close_j = j_start
                for j in range(j_start, min(j_end+1, len(tf_c))):
                    h=tf_c[j]['h']; l=tf_c[j]['l']
                    if trade_open['dir']=='buy':
                        if l<=trade_open['sl']: hit='sl'; close_j=j; break
                        if h>=trade_open['tp']: hit='tp'; close_j=j; break
                    else:
                        if h>=trade_open['sl']: hit='sl'; close_j=j; break
                        if l<=trade_open['tp']: hit='tp'; close_j=j; break
                trade_open['last_checked_j'] = min(j_end, len(tf_c)-1)
                if hit:
                    pnl_pts = trade_open['tp_pts'] if hit=='tp' else -trade_open['sl_pts']
                    pnl_usd = pnl_pts * trade_open['lot'] * 100
                    equity += pnl_usd
                    trade_open['result'] = hit; trade_open['pnl'] = pnl_usd
                    trade_open['close_t'] = tf_c[close_j]['t'] if close_j<len(tf_c) else h1_close_ts
                    trades.append(dict(trade_open))
                    equity_curve.append((trade_open['close_t'], equity))
                    cooldown_bars = 1
            if not hit:
                active_trades.append(trade_open)
        open_trades = active_trades

        if cooldown_bars > 0:
            cooldown_bars -= 1

        if len(open_trades) >= MAX_OPEN_TRADES: continue
        if cooldown_bars > 0: continue
        if trades_today >= MAX_TRADES_DAY: continue
        if not (SESSION[0] <= hour < SESSION[1]): continue

        reg = regime(ind_h1, i)
        if reg == 'EXTREME': continue

        strategies_for_regime = REGIME_MULTI_STRATEGIES.get(reg, [('S00_MFKK','H1',None)])
        open_dirs = {t['dir'] for t in open_trades}

        for (sname, tf, dir_filter) in strategies_for_regime:
            if len(open_trades) >= MAX_OPEN_TRADES: break
            if trades_today >= MAX_TRADES_DAY: break

            if tf == 'H1':
                use_ind=ind_h1; use_idx=i; use_atr=ind_h1['atr'][i] or 10.0
            elif tf == 'M15' and ind_m15:
                j=last_closed_idx(times_m15, h1_close_ts)
                if j<300: continue
                use_ind=ind_m15; use_idx=j; use_atr=ind_m15['atr'][j] or 10.0
            elif tf == 'M30' and ind_m30:
                j=last_closed_idx(times_m30, h1_close_ts)
                if j<250: continue
                use_ind=ind_m30; use_idx=j; use_atr=ind_m30['atr'][j] or 10.0
            else:
                use_ind=ind_h1; use_idx=i; use_atr=ind_h1['atr'][i] or 10.0

            fn = signal_fns.get(sname)
            if not fn: continue
            direction = fn(use_ind, use_idx)
            if not direction: continue
            if dir_filter and direction != dir_filter: continue
            if direction in open_dirs: continue

            ai_score = simulate_ai_score(use_ind, use_idx) if rm else 75.0
            if rm:
                params = rm.get_order_params(ai_score, use_atr, sname, direction)
                trade_lot=params['lot']
                # Applica moltiplicatori TP/SL personalizzati
                tp_pts = round(params['tp_usd'] * tp_mult / 1.5, 2)  # normalize vs base 1.5
                sl_pts = round(params['sl_usd'] * sl_mult / 1.0, 2)
            else:
                trade_lot=0.02
                tp_pts=round(use_atr*tp_mult, 2)
                sl_pts=round(use_atr*sl_mult, 2)

            entry_price = h1[i+1]['o']
            tp_p = entry_price+tp_pts if direction=='buy' else entry_price-tp_pts
            sl_p = entry_price-sl_pts if direction=='buy' else entry_price+sl_pts

            open_trades.append({
                'strategy':sname,'regime':reg,'tf':tf,'dir':direction,
                'entry':entry_price,'tp':tp_p,'sl':sl_p,
                'tp_pts':tp_pts,'sl_pts':sl_pts,'lot':trade_lot,
                'open_t':h1_open_ts,
                'open_bar_j':use_idx if tf!='H1' else i,
                'last_checked_j':use_idx if tf!='H1' else i,
            })
            open_dirs.add(direction)
            trades_today += 1

    for trade_open in open_trades:
        pnl_pts = h1[-1]['c'] - trade_open['entry'] if trade_open['dir']=='buy' \
              else trade_open['entry'] - h1[-1]['c']
        pnl_usd = round(pnl_pts * trade_open['lot'] * 100, 2)
        equity += pnl_usd
        trade_open.update({'result':'open','pnl':pnl_usd,'close_t':h1[-1]['t']})
        trades.append(dict(trade_open))

    return trades

def calc_stats(trades):
    if not trades: return None
    eq=0.0; peak=0.0; max_dd=0.0
    for t in trades:
        eq+=t['pnl']; peak=max(peak,eq); max_dd=max(max_dd,peak-eq)
    wins   = [t for t in trades if t.get('result')=='tp']
    losses = [t for t in trades if t.get('result')=='sl']
    wr     = len(wins)/len(trades)*100 if trades else 0
    gross_p = sum(t['pnl'] for t in wins)
    gross_l = abs(sum(t['pnl'] for t in losses))
    pf      = round(gross_p/gross_l, 3) if gross_l>0 else 99.0
    now_ts  = trades[-1]['close_t']
    def pnl_last(m):
        cutoff=now_ts-m*30*86400
        return round(sum(t['pnl'] for t in trades if t['close_t']>=cutoff),2)
    def tr_last(m):
        cutoff=now_ts-m*30*86400
        return len([t for t in trades if t['close_t']>=cutoff])
    peak_eq = 1000.0 + peak
    dd_pct  = round(max_dd/peak_eq*100,1) if peak_eq>0 else 0
    return {
        'wr':round(wr,1), 'pf':pf, 'n':len(trades),
        'pnl_1m':pnl_last(1), 'pnl_6m':pnl_last(6),
        'pnl_12m':pnl_last(12), 'pnl_24m':round(sum(t['pnl'] for t in trades),2),
        'trades_12m':tr_last(12), 'trades_1m':tr_last(1),
        'max_dd':round(max_dd,2), 'dd_pct':dd_pct,
        # Per strategia
        'by_strat': {k: {
            'n':len(v), 'wr':round(sum(1 for t in v if t.get('result')=='tp')/len(v)*100,1),
            'pnl':round(sum(t['pnl'] for t in v),2)
        } for k,v in {t['strategy']:[] for t in trades}.items()
          for _ in [None] if False} # placeholder, calcolato dopo
    }

def calc_stats_full(trades):
    if not trades: return None
    s = calc_stats(trades)
    by_strat={}
    for t in trades:
        by_strat.setdefault(t['strategy'],[]).append(t)
    s['by_strat'] = {k:{
        'n':len(v),
        'wr':round(sum(1 for t in v if t.get('result')=='tp')/len(v)*100,1),
        'pnl':round(sum(t['pnl'] for t in v),2)
    } for k,v in by_strat.items()}
    return s

# ──────────────────────────────────────────────────────────────────────────────
# GRID DI PARAMETRI
# ──────────────────────────────────────────────────────────────────────────────

# Fase 1: TP/SL ratio sweep (base line)
PHASE1_GRID = [
    # (tp_mult, sl_mult, label)
    (1.5, 1.0, 'TP1.5/SL1.0 [CURRENT]'),
    (1.2, 1.0, 'TP1.2/SL1.0'),
    (1.0, 1.0, 'TP1.0/SL1.0'),
    (1.0, 0.8, 'TP1.0/SL0.8'),
    (1.2, 0.8, 'TP1.2/SL0.8'),
    (1.5, 0.8, 'TP1.5/SL0.8'),
    (0.8, 0.8, 'TP0.8/SL0.8'),
    (2.0, 1.0, 'TP2.0/SL1.0'),
]

# Fase 2: segnali (con TP/SL fisso a 1.5/1.0 per comparabilità)
PHASE2_SIGNAL_COMBOS = [
    # (label, adx_i, rsi_b, ema_i, exhaust_rsi, ob_adx, ob_trend, struc_lb, struc_rp, struc_adx)
    ('CURRENT',          20, 0, False, 60, 0, False, 30, 0.002, 0),
    ('ADX22',            22, 0, False, 60, 0, False, 30, 0.002, 0),
    ('ADX25',            25, 0, False, 60, 0, False, 30, 0.002, 0),
    ('RSI+2',            20, 2, False, 60, 0, False, 30, 0.002, 0),
    ('RSI+5',            20, 5, False, 60, 0, False, 30, 0.002, 0),
    ('EMA_FILTER',       20, 0, True,  60, 0, False, 30, 0.002, 0),
    ('ADX22+RSI+2',      22, 2, False, 60, 0, False, 30, 0.002, 0),
    ('ADX22+EMA',        22, 0, True,  60, 0, False, 30, 0.002, 0),
    ('ADX25+RSI+2',      25, 2, False, 60, 0, False, 30, 0.002, 0),
    ('ADX25+EMA',        25, 0, True,  60, 0, False, 30, 0.002, 0),
    ('EXHAUST_RSI63',    20, 0, False, 63, 0, False, 30, 0.002, 0),
    ('EXHAUST_RSI65',    20, 0, False, 65, 0, False, 30, 0.002, 0),
    ('OB_ADX20',         20, 0, False, 60, 20, False, 30, 0.002, 0),
    ('OB_TREND',         20, 0, False, 60, 0, True,  30, 0.002, 0),
    ('STRUC_LB40',       20, 0, False, 60, 0, False, 40, 0.002, 0),
    ('STRUC_LB50',       20, 0, False, 60, 0, False, 50, 0.002, 0),
    ('STRUC_TIGHT',      20, 0, False, 60, 0, False, 30, 0.001, 0),
    ('STRUC_ADX20',      20, 0, False, 60, 0, False, 30, 0.002, 20),
    ('STRUC_LB40+ADX20', 20, 0, False, 60, 0, False, 40, 0.002, 20),
]

# Fase 3: combinazioni best segnali × best TP/SL
PHASE3_COMBOS = [
    # Prende le top 3 segnali × top 3 TP/SL dalla fase 1 e 2
    # Viene calcolato dinamicamente dopo le fasi 1 e 2
]

# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────
print("="*70)
print("TradeFlow AI — Parameter Optimization Study")
print("="*70)

print("\nCarico dati storici...")
h1  = load(args.h1)
m15 = load(args.m15)
m30 = load(args.m30)

if not h1:
    print("ERRORE: dati H1 non trovati.")
    sys.exit(1)

print(f"H1: {len(h1)} barre | M15: {len(m15)} barre | M30: {len(m30)} barre")
print("Precomputo indicatori (operazione singola)...")
ind_h1  = compute_ind(h1)
ind_m15 = compute_ind(m15) if m15 else None
ind_m30 = compute_ind(m30) if m30 else None
times_m15 = build_time_index(m15) if m15 else []
times_m30 = build_time_index(m30) if m30 else []
print("Indicatori pronti.\n")

all_results = []

# ──────────────────────────────────────────────────────────────────────────────
# FASE 1: TP/SL SWEEP
# ──────────────────────────────────────────────────────────────────────────────
if args.phase in ('1', 'all'):
    print("="*70)
    print("FASE 1: TP/SL Ratio Sweep (segnali invariati)")
    print("="*70)

    # Segnali base (current)
    base_fns = {
        'S05_V3_Sell_Exhaust': make_sell_exhaust(),
        'S05_MFKK_INTRADAY':   make_intraday(),
        'S10_OB_FVG_SCALP':    make_ob_fvg(),
        'S01_EXHAUSTION':      make_exhaustion(),
        'S09_MFKK_SCALPING':   make_scalping(),
        'S13_STRUC_BREAK':     make_struc_break(),
        'S00_MFKK':            make_mfkk_score(),
    }

    ph1_results = []
    for tp_m, sl_m, label in PHASE1_GRID:
        trades = run_sim(h1, m15, m30, ind_h1, ind_m15, ind_m30,
                         times_m15, times_m30, base_fns, tp_m, sl_m)
        s = calc_stats_full(trades)
        if not s: continue
        entry = {'phase':1, 'label':label, 'tp_mult':tp_m, 'sl_mult':sl_m, **s}
        ph1_results.append(entry)
        all_results.append(entry)

    ph1_results.sort(key=lambda x: (-x['wr'], -x['pnl_24m']))
    print(f"\n{'Label':<25} {'WR':>6} {'PF':>6} {'P&L 24m':>10} {'P&L 12m':>10} {'P&L 1m':>8} {'T/12m':>6} {'MaxDD':>8} {'DD%':>6}")
    print("-"*90)
    for r in ph1_results:
        marker = ' ◄ BEST' if r == ph1_results[0] else ''
        print(f"{r['label']:<25} {r['wr']:>5.1f}% {r['pf']:>6.3f} "
              f"${r['pnl_24m']:>9.0f} ${r['pnl_12m']:>9.0f} "
              f"${r['pnl_1m']:>7.0f} {r['trades_12m']:>6} "
              f"${r['max_dd']:>7.0f} {r['dd_pct']:>5.1f}%{marker}")

# ──────────────────────────────────────────────────────────────────────────────
# FASE 2: SEGNALI SWEEP (TP/SL fissi a 1.5/1.0)
# ──────────────────────────────────────────────────────────────────────────────
if args.phase in ('2', 'all'):
    print(f"\n{'='*70}")
    print("FASE 2: Segnali Sweep (TP=1.5×ATR / SL=1.0×ATR)")
    print("="*70)

    ph2_results = []
    for combo in PHASE2_SIGNAL_COMBOS:
        label, adx_i, rsi_b, ema_i, ex_rsi, ob_adx, ob_trend, struc_lb, struc_rp, struc_adx = combo
        fns = {
            'S05_V3_Sell_Exhaust': make_sell_exhaust(rsi_min=ex_rsi),
            'S05_MFKK_INTRADAY':   make_intraday(adx_min=adx_i, rsi_bias=rsi_b, ema_filter=ema_i),
            'S10_OB_FVG_SCALP':    make_ob_fvg(adx_filter=ob_adx, require_trend=ob_trend),
            'S01_EXHAUSTION':      make_exhaustion(),
            'S09_MFKK_SCALPING':   make_scalping(),
            'S13_STRUC_BREAK':     make_struc_break(lookback=struc_lb, retest_pct=struc_rp, adx_filter=struc_adx),
            'S00_MFKK':            make_mfkk_score(),
        }
        trades = run_sim(h1, m15, m30, ind_h1, ind_m15, ind_m30,
                         times_m15, times_m30, fns, 1.5, 1.0)
        s = calc_stats_full(trades)
        if not s: continue
        entry = {'phase':2, 'label':label, 'tp_mult':1.5, 'sl_mult':1.0,
                 'adx_i':adx_i, 'rsi_b':rsi_b, 'ema_i':ema_i, **s}
        ph2_results.append(entry)
        all_results.append(entry)

    ph2_results.sort(key=lambda x: (-x['wr'], -x['pnl_24m']))
    print(f"\n{'Label':<25} {'WR':>6} {'PF':>6} {'P&L 24m':>10} {'P&L 12m':>10} {'T/12m':>6} {'MaxDD%':>7}")
    print("-"*75)
    for r in ph2_results:
        marker = ' ◄ BEST' if r == ph2_results[0] else ''
        print(f"{r['label']:<25} {r['wr']:>5.1f}% {r['pf']:>6.3f} "
              f"${r['pnl_24m']:>9.0f} ${r['pnl_12m']:>9.0f} "
              f"{r['trades_12m']:>6} {r['dd_pct']:>6.1f}%{marker}")

    print("\nDettaglio top 5 segnali per strategia:")
    for r in ph2_results[:5]:
        print(f"\n  [{r['label']}]  WR={r['wr']}%  PF={r['pf']}  P&L_24m=${r['pnl_24m']}")
        for sn, sv in sorted(r.get('by_strat',{}).items(), key=lambda x:-x[1]['pnl']):
            print(f"    {sn:<25}  n={sv['n']:4d}  WR={sv['wr']:.1f}%  P&L=${sv['pnl']:.0f}")

# ──────────────────────────────────────────────────────────────────────────────
# FASE 3: MIGLIOR COMBINAZIONE (top segnali × top TP/SL)
# ──────────────────────────────────────────────────────────────────────────────
if args.phase in ('3', 'all') and len(all_results) > 0:
    print(f"\n{'='*70}")
    print("FASE 3: Combinazioni Best Segnali × Best TP/SL")
    print("="*70)

    # Prendi top 3 configurazioni segnali (fase 2) × top 3 TP/SL (fase 1)
    ph1_top = sorted([r for r in all_results if r['phase']==1],
                     key=lambda x: (-x['pnl_24m']))[:4]
    ph2_top = sorted([r for r in all_results if r['phase']==2],
                     key=lambda x: (-x['pnl_24m']))[:5]

    ph3_results = []
    combos_run = set()
    for r1 in ph1_top:
        for r2 in ph2_top:
            key = f"{r1['label']}+{r2['label']}"
            if key in combos_run: continue
            combos_run.add(key)
            adx_i = r2.get('adx_i', 20)
            rsi_b = r2.get('rsi_b', 0)
            ema_i = r2.get('ema_i', False)
            # Ricostruisce fns dal label di fase2
            combo = next((c for c in PHASE2_SIGNAL_COMBOS if c[0]==r2['label']), None)
            if not combo: continue
            _, adx_i, rsi_b, ema_i, ex_rsi, ob_adx, ob_trend, struc_lb, struc_rp, struc_adx = combo
            fns = {
                'S05_V3_Sell_Exhaust': make_sell_exhaust(rsi_min=ex_rsi),
                'S05_MFKK_INTRADAY':   make_intraday(adx_min=adx_i, rsi_bias=rsi_b, ema_filter=ema_i),
                'S10_OB_FVG_SCALP':    make_ob_fvg(adx_filter=ob_adx, require_trend=ob_trend),
                'S01_EXHAUSTION':      make_exhaustion(),
                'S09_MFKK_SCALPING':   make_scalping(),
                'S13_STRUC_BREAK':     make_struc_break(lookback=struc_lb, retest_pct=struc_rp, adx_filter=struc_adx),
                'S00_MFKK':            make_mfkk_score(),
            }
            trades = run_sim(h1, m15, m30, ind_h1, ind_m15, ind_m30,
                             times_m15, times_m30, fns, r1['tp_mult'], r1['sl_mult'])
            s = calc_stats_full(trades)
            if not s: continue
            label3 = f"{r1['label']} + {r2['label']}"
            entry = {'phase':3, 'label':label3, 'tp_mult':r1['tp_mult'], 'sl_mult':r1['sl_mult'], **s}
            ph3_results.append(entry)
            all_results.append(entry)

    ph3_results.sort(key=lambda x: (-x['pnl_24m']))
    print(f"\n{'Label':<50} {'WR':>6} {'PF':>6} {'P&L 24m':>10} {'P&L 12m':>10} {'T/12m':>6} {'MaxDD%':>7}")
    print("-"*100)
    for r in ph3_results:
        marker = ' ◄◄ BEST' if r == ph3_results[0] else ''
        print(f"{r['label']:<50} {r['wr']:>5.1f}% {r['pf']:>6.3f} "
              f"${r['pnl_24m']:>9.0f} ${r['pnl_12m']:>9.0f} "
              f"{r['trades_12m']:>6} {r['dd_pct']:>6.1f}%{marker}")

# ──────────────────────────────────────────────────────────────────────────────
# SOMMARIO FINALE
# ──────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*70}")
print("SOMMARIO: Top 10 configurazioni per P&L 24m")
print("="*70)
top10 = sorted(all_results, key=lambda x: -x['pnl_24m'])[:10]
print(f"\n{'#':<3} {'Label':<50} {'WR':>6} {'PF':>6} {'P&L 24m':>10} {'P&L 12m':>10} {'MaxDD%':>7}")
print("-"*100)
for idx, r in enumerate(top10, 1):
    print(f"{idx:<3} {r['label']:<50} {r['wr']:>5.1f}% {r['pf']:>6.3f} "
          f"${r['pnl_24m']:>9.0f} ${r['pnl_12m']:>9.0f} {r['dd_pct']:>6.1f}%")

print(f"\n{'='*70}")
print("Top 10 configurazioni per Win Rate")
print("="*70)
top_wr = sorted(all_results, key=lambda x: (-x['wr'], -x['pnl_24m']))[:10]
print(f"\n{'#':<3} {'Label':<50} {'WR':>6} {'PF':>6} {'P&L 24m':>10} {'T/12m':>6}")
print("-"*85)
for idx, r in enumerate(top_wr, 1):
    print(f"{idx:<3} {r['label']:<50} {r['wr']:>5.1f}% {r['pf']:>6.3f} "
          f"${r['pnl_24m']:>9.0f} {r['trades_12m']:>6}")

# SNIPPET CONFIGURAZIONE RACCOMANDATA
best = top10[0]
print(f"\n{'='*70}")
print(f"CONFIGURAZIONE RACCOMANDATA: {best['label']}")
print(f"{'='*70}")
print(f"  WR:       {best['wr']}%")
print(f"  PF:       {best['pf']}")
print(f"  P&L 24m:  ${best['pnl_24m']:.2f}")
print(f"  P&L 12m:  ${best['pnl_12m']:.2f}")
print(f"  P&L 1m:   ${best['pnl_1m']:.2f}")
print(f"  Trades/anno: {best['trades_12m']}")
print(f"  Max DD:   ${best['max_dd']:.2f} ({best['dd_pct']}%)")
print(f"  TP_MULT:  {best['tp_mult']}")
print(f"  SL_MULT:  {best['sl_mult']}")

# Salva risultati
with open(args.out, 'w', encoding='utf-8') as f:
    json.dump(all_results, f, indent=2)
print(f"\nRisultati salvati: {args.out}")
print(f"Totale combinazioni testate: {len(all_results)}")
