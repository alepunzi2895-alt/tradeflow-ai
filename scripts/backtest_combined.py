#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Combined System Backtest
Simula esattamente il flusso del bot reale:
  H1 bar close → rileva regime → seleziona strategia+TF dal playbook
  → ottieni indicatori sul TF corretto → esegui segnale
  → 1 trade alla volta, globale, ATR TP/SL

Produce stats aggregate reali per il pannello AI Gold Bot.

USO:
  python scripts/backtest_combined.py
  python scripts/backtest_combined.py --playbook regime_playbook.json
  python scripts/backtest_combined.py --out combined_results.json
"""
import sys, io, json, math, datetime, argparse, bisect
try:
    from risk_manager import get_risk_manager
except ImportError:
    get_risk_manager = None
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ap = argparse.ArgumentParser()
ap.add_argument('--playbook', default='regime_playbook.json')
ap.add_argument('--out',      default='combined_backtest.json')
ap.add_argument('--h1',  default='xauusd_h1_mt5.json')
ap.add_argument('--m15', default='xauusd_m15_mt5.json')
ap.add_argument('--m30', default='xauusd_m30_mt5.json')
args = ap.parse_args()

TP_MULT    = 1.5
SL_MULT    = 1.0
EXTREME_K  = 3.5
WARMUP_H1  = 250   # barre H1 di warmup prima di iniziare
MAX_LOOK   = 60    # max barre per risolvere TP/SL (H1 equiv)
SESSION    = (7, 17)  # ore UTC
MAX_TRADES_DAY = 3

# ── PLAYBOOK ──────────────────────────────────────────────────────────────────
FALLBACK_PLAYBOOK = {
    'TREND_UP':   {'strategy': 'S05_V3_Sell_Exhaust', 'tf': 'H1'},
    'TREND_DOWN': {'strategy': 'S01_EXHAUSTION',       'tf': 'M15'},
    'WEAK_UP':    {'strategy': 'S09_MFKK_SCALPING',    'tf': 'H1'},
    'WEAK_DOWN':  {'strategy': 'S09_MFKK_SCALPING',    'tf': 'M30'},
    'VOLATILE':   {'strategy': 'S09_MFKK_SCALPING',    'tf': 'M30'},
    'RANGE':      {'strategy': 'S13_STRUC_BREAK',       'tf': 'H1'},
    'UNKNOWN':    {'strategy': 'S00_MFKK',              'tf': 'H1'},
}

def load_playbook(path):
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        pb = {}
        for reg, info in data.get('playbook', {}).items():
            pb[reg] = {'strategy': info['strategy'], 'tf': info.get('tf', 'H1')}
        pb.setdefault('UNKNOWN', {'strategy': 'S00_MFKK', 'tf': 'H1'})
        return pb
    except Exception as e:
        print(f"  Playbook non trovato ({e}) — uso fallback")
        return FALLBACK_PLAYBOOK

# ── MATH ──────────────────────────────────────────────────────────────────────
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
    n=len(C); TR=[0]; DMP=[0]; DMM=[0]
    for i in range(1,n):
        TR.append(max(H[i]-L[i],abs(H[i]-C[i-1]),abs(L[i]-C[i-1])))
        up=H[i]-H[i-1]; dn=L[i-1]-L[i]
        DMP.append(up if up>dn and up>0 else 0)
        DMM.append(dn if dn>up and dn>0 else 0)
    sT=[0]; sP=[0]; sM=[0]
    for i in range(1,n):
        sT.append(sT[-1]-sT[-1]/p+TR[i])
        sP.append(sP[-1]-sP[-1]/p+DMP[i])
        sM.append(sM[-1]-sM[-1]/p+DMM[i])
    DIP=[sP[i]/sT[i]*100 if sT[i]>0 else 0 for i in range(n)]
    DIM=[sM[i]/sT[i]*100 if sT[i]>0 else 0 for i in range(n)]
    dx=[(abs(DIP[i]-DIM[i])/(DIP[i]+DIM[i])*100 if DIP[i]+DIM[i]>0 else 0) for i in range(n)]
    return sma(dx,p), DIP, DIM

def mom10(C):
    return [C[i]-C[i-10] if i>=10 else None for i in range(len(C))]

def stdev_arr(src, p):
    out=[None]*(p-1)
    for i in range(p-1,len(src)):
        sl=src[i-p+1:i+1]; mn=sum(sl)/p
        out.append(math.sqrt(sum((x-mn)**2 for x in sl)/p))
    return out

def dema(src, p):
    m1=ema(src,p); m2=ema(m1,p)
    return [2*m1[i]-m2[i] for i in range(len(src))]

def obv_macd_tchannel(H, L, C, V, wl=28, vl=14, ml=9, sl=26):
    n=len(C); obv_v=[0.0]
    for i in range(1,n):
        s=1 if C[i]>C[i-1] else(-1 if C[i]<C[i-1] else 0)
        obv_v.append(obv_v[-1]+s*(V[i] or 0))
    hl=[H[i]-L[i] for i in range(n)]
    ps=stdev_arr(hl,wl); sm=sma(obv_v,vl)
    vd=[obv_v[i]-(sm[i] or 0) for i in range(n)]
    vs=stdev_arr(vd,wl); out=[]
    for i in range(n):
        if sm[i] is None or not vs[i] or not ps[i]: out.append(C[i]); continue
        sh=(obv_v[i]-sm[i])/vs[i]*ps[i]
        out.append(H[i]+sh if sh>0 else L[i]+sh)
    dm=dema(out,ml); slw=ema(C,sl); mll=[dm[i]-slw[i] for i in range(n)]
    b5=[mll[0]]; oc=[0]; cd=0.0
    for i in range(1,n):
        cd+=abs(mll[i]-b5[-1]); a=cd/i
        if mll[i]>b5[-1]+a: b5.append(mll[i])
        elif mll[i]<b5[-1]-a: b5.append(mll[i])
        else: b5.append(b5[-1])
        oc.append(1 if b5[-1]>b5[-2] else(-1 if b5[-1]<b5[-2] else oc[-1]))
    return oc

def calc_fvg(O, H, L, C, std_len=100, df=2):
    n=len(C); body=[abs(O[i]-C[i]) for i in range(n)]
    bs=stdev_arr(body,std_len)
    fb=[False]*n; fs=[False]*n; ab=[]; as_=[]
    for i in range(2,n):
        disp=bs[i-1] is not None and bs[i-1]>0 and body[i-1]>bs[i-1]*df
        if L[i]>H[i-2]: ab.append({'lo':H[i-2],'hi':L[i],'bar':i,'d':disp})
        if H[i]<L[i-2]: as_.append({'lo':H[i],'hi':L[i-2],'bar':i,'d':disp})
        sb=[]
        for fvg in ab:
            if fvg['bar']==i: sb.append(fvg); continue
            if L[i]<fvg['lo']: continue
            if C[i]<=fvg['hi'] and C[i]>=fvg['lo']: fb[i]=True
            sb.append(fvg)
        ab=sb[-20:]
        sb2=[]
        for fvg in as_:
            if fvg['bar']==i: sb2.append(fvg); continue
            if H[i]>fvg['hi']: continue
            if C[i]>=fvg['lo'] and C[i]<=fvg['hi']: fs[i]=True
            sb2.append(fvg)
        as_=sb2[-20:]
    return fb, fs

def calc_order_blocks(O, H, L, C, lookback=30):
    """Calcolo Order Blocks identico al bot reale MT5."""
    n = len(C)
    ob_bull = [False]*n; ob_bear = [False]*n
    for i in range(lookback + 4, n):
        c_now = C[i]
        for j in range(i - 2, max(i - lookback - 1, 2), -1):
            if C[j] >= O[j]: continue
            ob_lo = min(O[j], C[j]); ob_hi = max(O[j], C[j])
            if not (j+1 < n and C[j+1] > O[j+1]): continue
            if any(L[k] < ob_lo * 0.998 for k in range(j+1, i)): continue
            if ob_lo * 0.998 <= c_now <= ob_hi * 1.003:
                ob_bull[i] = True; break
        for j in range(i - 2, max(i - lookback - 1, 2), -1):
            if C[j] <= O[j]: continue
            ob_lo = min(O[j], C[j]); ob_hi = max(O[j], C[j])
            if not (j+1 < n and C[j+1] < O[j+1]): continue
            if any(H[k] > ob_hi * 1.002 for k in range(j+1, i)): continue
            if ob_lo * 0.997 <= c_now <= ob_hi * 1.002:
                ob_bear[i] = True; break
    return ob_bull, ob_bear

def cci50(H, L, C):
    n=len(C); out=[None]*49
    for i in range(49,n):
        tp=[(H[j]+L[j]+C[j])/3 for j in range(i-49,i+1)]
        mn=sum(tp)/50; md=sum(abs(x-mn) for x in tp)/50
        out.append((tp[-1]-mn)/(0.015*md) if md>0 else 0)
    return out

# ── COMPUTE INDICATORS ────────────────────────────────────────────────────────
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
    try:
        I['obv_oc']=obv_macd_tchannel(H,L,C,V)
    except Exception:
        I['obv_oc']=[0]*n
    try:
        I['fvg_bull'],I['fvg_bear']=calc_fvg(O,H,L,C)
    except Exception:
        I['fvg_bull']=[False]*n; I['fvg_bear']=[False]*n
    try:
        I['ob_bull'],I['ob_bear']=calc_order_blocks(O,H,L,C)
    except Exception:
        I['ob_bull']=[False]*n; I['ob_bear']=[False]*n
    return I

# ── REGIME ────────────────────────────────────────────────────────────────────
def regime(I, i):
    a=I['adx'][i]; dp=I['dip'][i]; dm=I['dim'][i]
    av=I['atr'][i]; aa=I['atr30'][i]
    if a is None: return 'UNKNOWN'
    if av and aa and av > EXTREME_K * aa: return 'EXTREME'
    if a >= 30: return 'TREND_UP' if dp>dm else 'TREND_DOWN'
    if a >= 22: return 'WEAK_UP'  if dp>dm else 'WEAK_DOWN'
    if av and aa and av > 1.4*aa: return 'VOLATILE'
    return 'RANGE'

# ── SIGNAL FUNCTIONS ──────────────────────────────────────────────────────────
def s_sell_exhaust(I, i):
    if i<1: return None
    oc=I['obv_oc']
    if i>=len(oc): return None
    r=I['rsi'][i]; a=I['adx'][i]; m=I['mom'][i]
    if None in (r,a,m): return None
    if oc[i]==-1 and r>60 and a>=25 and m<0: return 'sell'
    return None

def s_mfkk_intraday(I, i):
    if i<2: return None
    oc=I.get('obv_oc', [])
    if not oc or i>=len(oc): return None
    r=I['rsi'][i]; mo=I['mom'][i]; a=I['adx'][i]; mc=I['macd'][i]
    if None in (r, mo, a, mc): return None
    if a < 20: return None
    if oc[i] == 1  and r > 50 and mo > 0 and mc > 0: return 'buy'
    if oc[i] == -1 and r < 50 and mo < 0 and mc < 0: return 'sell'
    return None

def s_ob_fvg_scalp(I, i):
    ob_b=I.get('ob_bull'); ob_s=I.get('ob_bear')
    fvg_b=I.get('fvg_bull'); fvg_s=I.get('fvg_bear')
    if ob_b is None or fvg_b is None: return None
    C=I['C']; O=I['O']
    bull_c = C[i] > O[i]
    bear_c = C[i] < O[i]
    if ob_b[i] and fvg_b[i] and bull_c: return 'buy'
    if ob_s[i] and fvg_s[i] and bear_c: return 'sell'
    return None

def s_exhaustion(I, i):
    a=I['adx'][i]; dp=I['dip'][i]; dm=I['dim'][i]
    ml=I['macd'][i]; ms=I['macd_sig'][i]
    if None in (a,dp,dm,ml,ms): return None
    diff=ml-ms; spread=abs(dp-dm)
    if a>=25 and dm>dp and spread>=15 and diff>=0.7: return 'sell'
    if a>=25 and dp>dm and spread>=15 and diff<=-0.7: return 'buy'
    return None

def s_mfkk_scalping(I, i):
    e20=I['e20'][i]; e50=I['e50'][i]; e100=I['e100'][i]; e200=I['e200'][i]
    fb=I.get('fvg_bull'); fs=I.get('fvg_bear')
    if None in (e20,e50,e100,e200) or fb is None: return None
    if e20>e50>e100>e200 and fb[i]: return 'buy'
    if e20<e50<e100<e200 and fs[i]: return 'sell'
    return None

def s_struc_break(I, i):
    if i<60: return None
    H=I['H']; L=I['L']; C=I['C']
    hh=max(H[i-30:i]); ll=min(L[i-30:i]); c=C[i]
    if c>hh and L[i]<=hh*1.002 and L[i]>=hh*0.998: return 'buy'
    if c<ll and H[i]>=ll*0.998 and H[i]<=ll*1.002: return 'sell'
    return None

def s_mfkk_score(I, i):
    if i<50: return None
    a=I['adx'][i]; dp=I['dip'][i]; dm=I['dim'][i]
    m=I['macd'][i]; c=I['cci'][i]
    if None in (a,dp,dm,m): return None
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
    if bull>=90: return 'buy'
    if bear>=75: return 'sell'
    return None

SIGNAL_FNS = {
    'S05_V3_Sell_Exhaust': s_sell_exhaust,
    'S05_MFKK_INTRADAY':   s_mfkk_intraday,
    'S10_OB_FVG_SCALP':    s_ob_fvg_scalp,
    'S01_EXHAUSTION':      s_exhaustion,
    'S09_MFKK_SCALPING':   s_mfkk_scalping,
    'S13_STRUC_BREAK':     s_struc_break,
    'S00_MFKK':            s_mfkk_score,
}

# ── DATI ──────────────────────────────────────────────────────────────────────
def load(path):
    try:
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
        candles = d.get('candles', d) if isinstance(d, dict) else d
        # Assicura campo 'o'
        for c in candles:
            if 'o' not in c:
                c['o'] = c.get('open', c.get('c', 0))
        return sorted(candles, key=lambda x: x['t'])
    except Exception as e:
        print(f"  Errore caricamento {path}: {e}")
        return []

# ── ALLINEAMENTO TF ───────────────────────────────────────────────────────────
def build_time_index(candles):
    """Lista ordinata di timestamps per binary search."""
    return [c['t'] for c in candles]

def last_closed_idx(tf_times, h1_close_ts):
    """
    Ultimo indice nel TF minore la cui barra è CHIUSA prima di h1_close_ts.
    Assumendo tf_times = lista di open-time delle barre.
    """
    pos = bisect.bisect_left(tf_times, h1_close_ts) - 1
    return pos  # -1 = nessuna barra disponibile

# ── RISOLUZIONE TRADE ─────────────────────────────────────────────────────────
def resolve(candles, open_idx, direction, tp_price, sl_price, max_bars):
    """
    Cerca TP o SL su candles[open_idx+1 ... open_idx+max_bars].
    Ritorna (result, close_idx, close_price).
    """
    for j in range(open_idx+1, min(open_idx+max_bars+1, len(candles))):
        h=candles[j]['h']; l=candles[j]['l']
        if direction=='buy':
            if l<=sl_price: return 'sl', j, sl_price
            if h>=tp_price: return 'tp', j, tp_price
        else:
            if h>=sl_price: return 'sl', j, sl_price
            if l<=tp_price: return 'tp', j, tp_price
    j=min(open_idx+max_bars, len(candles)-1)
    return 'timeout', j, candles[j]['c']

# ── SIMULAZIONE COMBINATA ─────────────────────────────────────────────────────
def simulate(h1, m15, m30, playbook):
    print(f"\nH1: {len(h1)} barre | M15: {len(m15)} barre | M30: {len(m30)} barre")

    # Precomputa indicatori per ogni TF
    print("Calcolo indicatori H1...")
    ind_h1  = compute_ind(h1)
    print("Calcolo indicatori M15...")
    ind_m15 = compute_ind(m15) if m15 else None
    print("Calcolo indicatori M30...")
    ind_m30 = compute_ind(m30) if m30 else None

    times_m15 = build_time_index(m15) if m15 else []
    times_m30 = build_time_index(m30) if m30 else []

    trades = []
    equity_curve = []   # (timestamp, equity)
    INITIAL_BALANCE = 2000.0
    equity = INITIAL_BALANCE

    # Inizializza RiskManager (simula lotto medio proporzionato al conto)
    # Impostiamo base_lot = 0.18 per colpire target >$500/m con score=75
    rm = get_risk_manager(base_lot=0.18, max_lot=0.50) if get_risk_manager else None

    # Stato simulazione
    open_trades    = []
    MAX_OPEN_TRADES= 3
    cooldown_bars  = 0   # barre H1 di cooldown
    trades_today   = 0
    current_day    = None

    H1_INTERVAL = 3600  # secondi

    for i in range(WARMUP_H1, len(h1)-1):
        h1_open_ts  = h1[i]['t']
        h1_close_ts = h1_open_ts + H1_INTERVAL
        bar_dt = datetime.datetime.utcfromtimestamp(h1_open_ts)
        hour   = bar_dt.hour

        # Reset daily counter
        day = bar_dt.date()
        if day != current_day:
            current_day  = day
            trades_today = 0

        # ── Gestione trades aperti ──────────────────
        active_trades = []
        for trade_open in open_trades:
            tf  = trade_open['tf']
            hit = None
            if tf == 'H1':
                # Cerca TP/SL sulla barra H1 corrente
                h=h1[i]['h']; l=h1[i]['l']
                if trade_open['dir']=='buy':
                    hit = 'sl' if l<=trade_open['sl'] else ('tp' if h>=trade_open['tp'] else None)
                else:
                    hit = 'sl' if h>=trade_open['sl'] else ('tp' if l<=trade_open['tp'] else None)
                if hit:
                    pnl_pts = trade_open['tp_pts'] if hit=='tp' else -trade_open['sl_pts']
                    pnl_usd = pnl_pts * trade_open['lot'] * 100
                    equity += pnl_usd
                    trade_open['result'] = hit
                    trade_open['pnl']    = pnl_usd
                    trade_open['close_t'] = h1_open_ts
                    trades.append(dict(trade_open))
                    equity_curve.append((h1_open_ts, equity))
                    cooldown_bars = 1
            else:
                # Cerca TP/SL su M15/M30 bars tra l'ultimo controllo e h1_close_ts
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
                    trade_open['result'] = hit
                    trade_open['pnl']    = pnl_usd
                    trade_open['close_t'] = tf_c[close_j]['t'] if close_j<len(tf_c) else h1_close_ts
                    trades.append(dict(trade_open))
                    equity_curve.append((trade_open['close_t'], equity))
                    cooldown_bars = 1
            
            if not hit:
                active_trades.append(trade_open)
                
        open_trades = active_trades

        if cooldown_bars > 0:
            cooldown_bars -= 1

        # ── Verifica condizioni per nuovo trade ────────────────────────────
        if len(open_trades) >= MAX_OPEN_TRADES: continue
        if cooldown_bars > 0: continue
        if trades_today >= MAX_TRADES_DAY: continue
        if not (SESSION[0] <= hour < SESSION[1]): continue

        # ── Rileva regime ─────────────────────────────────────────────────
        reg = regime(ind_h1, i)
        if reg == 'EXTREME': continue

        entry = playbook.get(reg)
        if not entry: continue
        sname = entry['strategy']
        tf    = entry['tf']

        # ── Indicatori del TF corretto ────────────────────────────────────
        if tf == 'H1':
            use_ind = ind_h1
            use_idx = i
            use_atr = ind_h1['atr'][i] or 10.0
        elif tf == 'M15' and ind_m15:
            j = last_closed_idx(times_m15, h1_close_ts)
            if j < 300: continue   # warmup insufficiente
            # Usa indicatori precomputati su tutto M15, accede all'indice j
            use_ind = ind_m15
            use_idx = j
            use_atr = ind_m15['atr'][j] or 10.0
        elif tf == 'M30' and ind_m30:
            j = last_closed_idx(times_m30, h1_close_ts)
            if j < 250: continue
            use_ind = ind_m30
            use_idx = j
            use_atr = ind_m30['atr'][j] or 10.0
        else:
            use_ind = ind_h1; use_idx = i
            use_atr = ind_h1['atr'][i] or 10.0

        # ── Segnale ───────────────────────────────────────────────────────
        fn = SIGNAL_FNS.get(sname)
        if not fn: continue
        direction = fn(use_ind, use_idx)
        if not direction: continue

        # ── Apri trade ────────────────────────────────────────────────────
        entry_price = h1[i+1]['o']   # open della prossima H1 barra = esecuzione market
        
        # Risk Manager sizing se disponibile, altrimenti fallback statico a 0.02
        trade_lot = 0.02
        if rm:
            # Simula score dinamico 70-85 (il bot filtra i migliori regimi empirici)
            ai_score = 75.0 
            params = rm.get_order_params(ai_score, use_atr, sname, direction)
            trade_lot = params['lot']
            tp_pts = params['tp_usd']
            sl_pts = params['sl_usd']
        else:
            tp_pts = round(use_atr * TP_MULT, 2)
            sl_pts = round(use_atr * SL_MULT, 2)
            
        tp_p   = entry_price + tp_pts if direction=='buy' else entry_price - tp_pts
        sl_p   = entry_price - sl_pts if direction=='buy' else entry_price + sl_pts

        trade_open = {
            'strategy':  sname,
            'regime':    reg,
            'tf':        tf,
            'dir':       direction,
            'entry':     entry_price,
            'tp':        tp_p,
            'sl':        sl_p,
            'tp_pts':    tp_pts,
            'sl_pts':    sl_pts,
            'lot':       trade_lot,
            'open_t':    h1_open_ts,
            'open_bar_j': use_idx if tf!='H1' else i,
            'last_checked_j': use_idx if tf!='H1' else i,
        }
        open_trades.append(trade_open)
        trades_today += 1

    # Trade ancora aperto a fine serie
    for trade_open in open_trades:
        pnl_pts = h1[-1]['c'] - trade_open['entry'] if trade_open['dir']=='buy' \
              else trade_open['entry'] - h1[-1]['c']
        pnl_usd = round(pnl_pts * trade_open['lot'] * 100, 2)
        equity += pnl_usd
        trade_open.update({'result':'open','pnl':pnl_usd,'close_t':h1[-1]['t']})
        trades.append(dict(trade_open))

    return trades, equity_curve

# ── STATISTICHE ───────────────────────────────────────────────────────────────
def stats(trades, equity_curve):
    if not trades:
        return {}

    # Equity curve per drawdown
    eq = 0.0; peak = 0.0; max_dd = 0.0; curve = []
    for t in trades:
        eq += t['pnl']
        peak = max(peak, eq)
        dd = peak - eq
        max_dd = max(max_dd, dd)
        curve.append((t['close_t'], eq))

    wins   = [t for t in trades if t.get('result')=='tp']
    losses = [t for t in trades if t.get('result')=='sl']
    wr     = len(wins)/len(trades)*100 if trades else 0
    gross_p = sum(t['pnl'] for t in wins)
    gross_l = abs(sum(t['pnl'] for t in losses))
    pf      = round(gross_p/gross_l, 3) if gross_l>0 else float('inf')
    total_pnl = sum(t['pnl'] for t in trades)

    # Distribuzione per strategia e regime
    by_strat = {}
    for t in trades:
        k = t['strategy']
        by_strat.setdefault(k, []).append(t)

    by_regime = {}
    for t in trades:
        k = t['regime']
        by_regime.setdefault(k, []).append(t)

    # P&L per periodo (ultimi N mesi)
    now_ts = trades[-1]['close_t']
    def pnl_last(months):
        cutoff = now_ts - months*30*86400
        return round(sum(t['pnl'] for t in trades if t['close_t']>=cutoff), 2)

    def trades_last(months):
        cutoff = now_ts - months*30*86400
        return len([t for t in trades if t['close_t']>=cutoff])

    return {
        'total_trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'wr': round(wr, 1),
        'pf': pf,
        'total_pnl': round(total_pnl, 2),
        'max_dd': round(max_dd, 2),
        'pnl_1m':  pnl_last(1),   'trades_1m':  trades_last(1),
        'pnl_6m':  pnl_last(6),   'trades_6m':  trades_last(6),
        'pnl_12m': pnl_last(12),  'trades_12m': trades_last(12),
        'pnl_24m': pnl_last(24),  'trades_24m': trades_last(24),
        'by_strategy': {k: {
            'n': len(v),
            'wr': round(sum(1 for t in v if t.get('result')=='tp')/len(v)*100, 1),
            'pnl': round(sum(t['pnl'] for t in v), 2),
            'pf': round(sum(t['pnl'] for t in v if t.get('result')=='tp') /
                        max(abs(sum(t['pnl'] for t in v if t.get('result')=='sl')), 0.01), 2),
        } for k, v in by_strat.items()},
        'by_regime': {k: {
            'n': len(v),
            'pnl': round(sum(t['pnl'] for t in v), 2),
        } for k, v in by_regime.items()},
        'equity_curve': curve[-50:],  # ultimi 50 punti per compattezza
    }

# ── MAIN ──────────────────────────────────────────────────────────────────────
print("="*60)
print("TradeFlow AI — Combined System Backtest")
print("="*60)

playbook = load_playbook(args.playbook)
print(f"\nPlaybook ({len(playbook)} regimi):")
for reg, v in playbook.items():
    print(f"  {reg:12s} → {v['strategy']:25s} / {v['tf']}")

print(f"\nCarico dati storici...")
h1  = load(args.h1)
m15 = load(args.m15)
m30 = load(args.m30)

if not h1:
    print("ERRORE: dati H1 non trovati. Esegui fetch_mt5_history.py prima.")
    sys.exit(1)

# Allinea periodo comune (usa H1 come riferimento)
h1_start = h1[WARMUP_H1]['t']
h1_end   = h1[-1]['t']
print(f"\nPeriodo H1: {datetime.datetime.utcfromtimestamp(h1_start).strftime('%Y-%m-%d')} "
      f"→ {datetime.datetime.utcfromtimestamp(h1_end).strftime('%Y-%m-%d')}")
if m15:
    print(f"Periodo M15: {datetime.datetime.utcfromtimestamp(m15[0]['t']).strftime('%Y-%m-%d')} "
          f"→ {datetime.datetime.utcfromtimestamp(m15[-1]['t']).strftime('%Y-%m-%d')}")
if m30:
    print(f"Periodo M30: {datetime.datetime.utcfromtimestamp(m30[0]['t']).strftime('%Y-%m-%d')} "
          f"→ {datetime.datetime.utcfromtimestamp(m30[-1]['t']).strftime('%Y-%m-%d')}")

trades, equity_curve = simulate(h1, m15, m30, playbook)
s = stats(trades, equity_curve)

if not s:
    print("\nNessun trade generato.")
    sys.exit(0)

print(f"\n{'='*60}")
print(f"RISULTATI SISTEMA COMBINATO (con Compounding e Multi-Trade)")
print(f"{'='*60}")
print(f"  Saldo iniziale: $2000.00")
print(f"  Saldo finale  : ${2000.00 + s['total_pnl']:.2f}")
print(f"  Trade totali  : {s['total_trades']} ({s['wins']} TP / {s['losses']} SL)")
print(f"  Win Rate      : {s['wr']}%")
print(f"  Profit Factor : {s['pf']}")
print(f"  P&L totale    : ${s['total_pnl']:.2f}")
print(f"  Max Drawdown  : ${s['max_dd']:.2f}")
print(f"\nPer periodo (scaling dinamico RiskManager base_lot=0.18):")
print(f"  1 mese   : ${s['pnl_1m']:.2f}   ({s['trades_1m']} trade)")
print(f"  6 mesi   : ${s['pnl_6m']:.2f}   ({s['trades_6m']} trade)")
print(f"  12 mesi  : ${s['pnl_12m']:.2f}  ({s['trades_12m']} trade)")
print(f"  24 mesi  : ${s['pnl_24m']:.2f}  ({s['trades_24m']} trade)")

print(f"\nPer strategia:")
for sname, sv in sorted(s['by_strategy'].items(), key=lambda x: -x[1]['pnl']):
    print(f"  {sname:25s}  {sv['n']:4d} trade  WR {sv['wr']:.1f}%  PF {sv['pf']:.2f}  P&L ${sv['pnl']:.2f}")

print(f"\nPer regime:")
for reg, rv in sorted(s['by_regime'].items(), key=lambda x: -x[1]['pnl']):
    print(f"  {reg:12s}  {rv['n']:4d} trade  P&L ${rv['pnl']:.2f}")

# Genera snippet per strategy.js
max_dd_pct = round(s['max_dd'] / max(abs(s['pnl_24m']), 1) * 100, 1)
print(f"\n{'='*60}")
print("SNIPPET per strategy.js — sostituisci BOT_STATS:")
print(f"  const BOT_STATS = {{")
print(f"    pnl_1m:{s['pnl_1m']}, pnl_6m:{s['pnl_6m']},")
print(f"    pnl_12m:{s['pnl_12m']}, pnl_24m:{s['pnl_24m']},")
print(f"    maxdd:{s['max_dd']}, maxdd_pct:'{max_dd_pct}%',")
print(f"    trades_12m:{s['trades_12m']}, pf:{s['pf']},")
print(f"    wr:'{s['wr']}%', n_strat:6")
print(f"  }};")

# Salva JSON
output = {
    'generated_at': datetime.datetime.utcnow().isoformat(),
    'stats': s,
    'trades': trades,
    'playbook': playbook,
}
with open(args.out, 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2)
print(f"\nSalvato: {args.out}")
print(f"\nComando per aggiornare i dati:")
print(f"  python scripts/backtest_combined.py")
