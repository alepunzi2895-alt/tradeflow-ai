#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Backtest OBV MACD + RSI + Momentum
Multi-timeframe, 6 varianti strategiche, 2 anni di storia XAU/USD

USO:
  # Solo H1 da file JSON (nessun MT5 necessario)
  python scripts/backtest_obv_rsi_mom.py --h1-file xauusd_h1_730d.json

  # Multi-TF con MT5 aperto (scarica tutti i TF automaticamente)
  python scripts/backtest_obv_rsi_mom.py --mt5

  # Multi-TF da file pre-scaricati
  python scripts/backtest_obv_rsi_mom.py \
    --h1-file xauusd_h1_mt5.json \
    --h4-file xauusd_h4_mt5.json \
    --d1-file xauusd_d1_mt5.json

OUTPUT: backtest_obv_rsi_mom.json — ranking completo con best strategy per TF
"""
import sys, io, argparse, json, math, datetime, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from collections import defaultdict

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
MT5_LOGIN    = 1301224666
MT5_PASSWORD = "Alessandro95!"
MT5_SERVER   = "XMGlobal-MT5 6"
SYMBOL_CANDIDATES = ["GOLD", "XAUUSD", "XAUUSD.m"]

DAYS        = 730
TP_ATR_MULT = 2.0     # TP = 2x ATR
SL_ATR_MULT = 1.0     # SL = 1x ATR
MAX_TRADES  = 8       # max trade/giorno per TF
EXTREME_K   = 3.5     # ATR > 3.5x media30 = sospendi
SESSION     = (0, 24) # 24h (cambieremo per TF specifici)

# Timeframes con parametri specifici
TF_CONFIG = {
    'M15': {'label': 'M15',  'cooldown_bars': 4,  'min_trades': 50,  'session': (7,22)},
    'M30': {'label': 'M30',  'cooldown_bars': 2,  'min_trades': 40,  'session': (7,22)},
    'H1':  {'label': 'H1',   'cooldown_bars': 1,  'min_trades': 30,  'session': (0,24)},
    'H4':  {'label': 'H4',   'cooldown_bars': 1,  'min_trades': 15,  'session': (0,24)},
    'D1':  {'label': 'D1',   'cooldown_bars': 1,  'min_trades': 8,   'session': (0,24)},
}

# ─────────────────────────────────────────────────────────────────────────────
# ARGPARSE
# ─────────────────────────────────────────────────────────────────────────────
ap = argparse.ArgumentParser(description='Backtest OBV MACD + RSI + Momentum')
ap.add_argument('--mt5',      action='store_true', help='Connetti MT5 per tutti i TF')
ap.add_argument('--h1-file',  type=str, default=None)
ap.add_argument('--m15-file', type=str, default=None)
ap.add_argument('--m30-file', type=str, default=None)
ap.add_argument('--h4-file',  type=str, default=None)
ap.add_argument('--d1-file',  type=str, default=None)
ap.add_argument('--out',      type=str, default='backtest_obv_rsi_mom.json')
args = ap.parse_args()

# ─────────────────────────────────────────────────────────────────────────────
# INDICATORI BASE
# ─────────────────────────────────────────────────────────────────────────────
def ema(src, p):
    k=2/(p+1); v=src[0]; o=[v]
    for x in src[1:]: v=x*k+v*(1-k); o.append(v)
    return o

def sma(src, p):
    o=[None]*(p-1)
    for i in range(p-1,len(src)):
        o.append(sum(src[i-p+1:i+1])/p)
    return o

def stdev_arr(src, p):
    out=[None]*(p-1)
    for i in range(p-1,len(src)):
        sl=src[i-p+1:i+1]
        mn=sum(sl)/p
        out.append(math.sqrt(sum((x-mn)**2 for x in sl)/p))
    return out

def dema(src, p):
    m1=ema(src,p); m2=ema(m1,p)
    return [2*m1[i]-m2[i] for i in range(len(src))]

def rsi(src, p=14):
    n=len(src); out=[None]*n
    g=[max(0,src[i]-src[i-1]) for i in range(1,n)]
    lo=[max(0,src[i-1]-src[i]) for i in range(1,n)]
    if len(g)<p: return out
    ag=sum(g[:p])/p; al=sum(lo[:p])/p
    out[p]=100-100/(1+(ag/al if al>0 else 100))
    for i in range(p,len(g)):
        ag=(ag*(p-1)+g[i])/p; al=(al*(p-1)+lo[i])/p
        out[i+1]=100-100/(1+(ag/al if al>0 else 100))
    return out

def momentum_roc(src, p=10):
    """Rate of Change %"""
    out=[None]*p
    for i in range(p,len(src)):
        out.append((src[i]-src[i-p])/src[i-p]*100 if src[i-p]!=0 else 0)
    return out

def atr_calc(H, L, C, p=14):
    tr=[0]
    for i in range(1,len(C)):
        tr.append(max(H[i]-L[i],abs(H[i]-C[i-1]),abs(L[i]-C[i-1])))
    return sma(tr,p)

# ─────────────────────────────────────────────────────────────────────────────
# OBV MACD T-CHANNEL
# ─────────────────────────────────────────────────────────────────────────────
def obv_macd_tchannel(H, L, C, V, wl=28, vl=14, ml=9, sl=26):
    """
    Traduzione fedele Pine Script v4 OBV MACD.
    Ritorna (macd_line, b5_channel, oc_direction)
    oc: 1=bull, -1=bear
    """
    n=len(C)
    # OBV
    obv=[0.0]
    for i in range(1,n):
        s=1 if C[i]>C[i-1] else (-1 if C[i]<C[i-1] else 0)
        obv.append(obv[-1]+s*(V[i] or 0))
    # Normalizzazione price-scale
    hl=[H[i]-L[i] for i in range(n)]
    ps=stdev_arr(hl,wl)
    sm=sma(obv,vl)
    vd=[obv[i]-(sm[i] or 0) for i in range(n)]
    vs=stdev_arr(vd,wl)
    out=[]
    for i in range(n):
        if sm[i] is None or not vs[i] or not ps[i]: out.append(C[i]); continue
        sh=(obv[i]-sm[i])/vs[i]*ps[i]
        out.append(H[i]+sh if sh>0 else L[i]+sh)
    # DEMA(9) + MACD
    dm=dema(out,ml); slw=ema(C,sl)
    ml_=[dm[i]-slw[i] for i in range(n)]
    # T-Channel
    b5=[ml_[0]]; oc=[0]; cd=0.0
    for i in range(1,n):
        cd+=abs(ml_[i]-b5[-1])
        a=cd/i
        if   ml_[i]>b5[-1]+a: b5.append(ml_[i])
        elif ml_[i]<b5[-1]-a: b5.append(ml_[i])
        else: b5.append(b5[-1])
        if   b5[-1]>b5[-2]: oc.append(1)
        elif b5[-1]<b5[-2]: oc.append(-1)
        else: oc.append(oc[-1])
    return ml_,b5,oc

# ─────────────────────────────────────────────────────────────────────────────
# COMPUTE INDICATORS
# ─────────────────────────────────────────────────────────────────────────────
def adx_calc(H, L, C, p=14):
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
    DX=[abs(DIP[i]-DIM[i])/(DIP[i]+DIM[i])*100 if (DIP[i]+DIM[i])>0 else 0 for i in range(n)]
    return sma(DX,p), DIP, DIM

def macd_line(C, fast=12, slow=26):
    ef=ema(C,fast); es=ema(C,slow)
    return [ef[i]-es[i] for i in range(len(C))]

def compute(candles):
    H=[c['h'] for c in candles]; L=[c['l'] for c in candles]
    C=[c['c'] for c in candles]; V=[c['v'] for c in candles]
    n=len(C)
    r14   = rsi(C,14)
    mom10 = momentum_roc(C,10)
    mom5  = momentum_roc(C,5)
    atr14 = atr_calc(H,L,C,14)
    atr30 = sma([x if x else 0 for x in atr14],30)
    adx,dip,dim = adx_calc(H,L,C,14)
    macd = macd_line(C)
    e20  = ema(C,20); e50 = ema(C,50)
    ml,b5,oc = obv_macd_tchannel(H,L,C,V)
    return {
        'n':n,'H':H,'L':L,'C':C,'V':V,
        'rsi':r14,'mom10':mom10,'mom5':mom5,
        'atr':atr14,'atr30':atr30,
        'adx':adx,'dip':dip,'dim':dim,
        'macd':macd,'e20':e20,'e50':e50,
        'obv_ml':ml,'obv_b5':b5,'obv_oc':oc,
    }

# ─────────────────────────────────────────────────────────────────────────────
# 6 VARIANTI STRATEGIA
# ─────────────────────────────────────────────────────────────────────────────

def v1_flip_rsi_mom(ind, i):
    """
    V1 — OBV FLIP + RSI + MOMENTUM + ADX TREND
    Flip del T-Channel confermato da RSI non saturo,
    momentum allineato, ADX >= 18 (trend presente).
    """
    if i<1: return None
    oc=ind['obv_oc']; r=ind['rsi'][i]; m=ind['mom10'][i]; a=ind['adx'][i]
    if None in (r,m,a): return None
    if oc[i]==1  and oc[i-1]!=1  and r<62 and m>0 and a>=18: return 'buy'
    if oc[i]==-1 and oc[i-1]!=-1 and r>38 and m<0 and a>=18: return 'sell'
    return None

def v2_triple_align_adx(ind, i):
    """
    V2 — TRIPLA CONFLUENZA + ADX + MACD CONFERMA
    OBV direzione + RSI lato giusto + Momentum + ADX >= 20 + MACD allineato.
    Trend-following con 4 conferme.
    """
    if i<3: return None
    oc=ind['obv_oc']; r=ind['rsi'][i]; m=ind['mom10'][i]
    a=ind['adx'][i]; mc=ind['macd'][i]
    if None in (r,m,a,mc): return None
    if a<20: return None
    if oc[i]==1  and r>50 and m>0 and mc>0: return 'buy'
    if oc[i]==-1 and r<50 and m<0 and mc<0: return 'sell'
    return None

def v3_flip_rsi_extreme_adx(ind, i):
    """
    V3 — OBV FLIP + RSI ESAURIMENTO + ADX TREND
    Il volume si inverte mentre il prezzo è esteso E c'è trend.
    Bias SELL: RSI > 60 con trend ribassista = esaurimento rialzista.
    """
    if i<1: return None
    oc=ind['obv_oc']; r=ind['rsi'][i]; a=ind['adx'][i]
    dip=ind['dip'][i]; dim=ind['dim'][i]
    if None in (r,a,dip,dim): return None
    # BUY: OBV flip al rialzo + RSI oversold + trend bearish in esaurimento
    if oc[i]==1 and oc[i-1]!=1 and r<38 and a>=20:  return 'buy'
    # SELL: OBV flip al ribasso + RSI overbought + trend bullish in esaurimento
    if oc[i]==-1 and oc[i-1]!=-1 and r>62 and a>=20: return 'sell'
    return None

def v4_sell_exhaustion_obv(ind, i):
    """
    V4 — SELL EXHAUSTION ONLY (bias ribassista XAU)
    Sul Gold SELL >> BUY storicamente. Questa variante è SELL ONLY.
    OBV in stato ribassista (non solo flip) + RSI > 55 + ADX >= 20 + Momentum negativo.
    Non richiede MACD già negativo (OBV anticipa MACD).
    """
    if i<1: return None
    oc=ind['obv_oc']; r=ind['rsi'][i]; a=ind['adx'][i]; m=ind['mom10'][i]
    if None in (r,a,m): return None
    # OBV bearish (sia flip che stato sostenuto) + RSI sopra 55 + ADX + Mom negativo
    if oc[i]==-1 and r>55 and a>=20 and m<0: return 'sell'
    return None

def v5_momentum_session(ind, i):
    """
    V5 — OBV FLIP + MOMENTUM FORTE + SESSIONE LONDON/NY
    Segnale solo nelle ore di maggiore liquidità (7-17 UTC).
    OBV flip + RSI + ADX + Momentum.
    Il timing della sessione filtra i falsi segnali asiatici.
    """
    if i<3: return None
    oc=ind['obv_oc']; r=ind['rsi'][i]; m=ind['mom10']; a=ind['adx'][i]
    if None in (r,m[i],m[i-2],a): return None
    mom_up  = m[i]>0 and m[i]>m[i-2]
    mom_dn  = m[i]<0 and m[i]<m[i-2]
    if oc[i]==1  and oc[i-1]!=1  and r<60 and a>=18 and mom_up: return 'buy'
    if oc[i]==-1 and oc[i-1]!=-1 and r>40 and a>=18 and mom_dn: return 'sell'
    return None

def v6_strong_signal(ind, i):
    """
    V6 — SEGNALE FORTE (5 condizioni)
    Richiede OBV flip + RSI zona + ADX alto + MACD + Momentum + prezzo sopra/sotto EMA.
    Meno trade ma molto più selettivi. Ottimo per H4/D1.
    """
    if i<2: return None
    oc=ind['obv_oc']; r=ind['rsi'][i]; a=ind['adx'][i]
    mc=ind['macd']; m=ind['mom10'][i]; c=ind['C'][i]; e50=ind['e50'][i]
    if None in (r,a,mc[i],mc[i-1],m,e50): return None
    macd_flip_up = mc[i]>0 and mc[i-1]<=0
    macd_flip_dn = mc[i]<0 and mc[i-1]>=0
    if oc[i]==1  and oc[i-1]!=1  and r<58 and a>=25 and (macd_flip_up or mc[i]>0) and m>0 and c>e50: return 'buy'
    if oc[i]==-1 and oc[i-1]!=-1 and r>42 and a>=25 and (macd_flip_dn or mc[i]<0) and m<0 and c<e50: return 'sell'
    return None

def v7_sell_flip_rsi_macd(ind, i):
    """
    V7 — SELL ONLY: OBV FLIP + RSI OVERBOUGHT + MACD CONFERMA
    Ingresso SELL al flip OBV se RSI è sopra 55 E MACD era bullish (esaurimento).
    Logica: il volume si distribuisce mentre il prezzo è ancora alto = top picking.
    """
    if i<2: return None
    oc=ind['obv_oc']; r=ind['rsi'][i]; mc=ind['macd']; a=ind['adx'][i]; m=ind['mom10'][i]
    if None in (r,mc[i],mc[i-1],a,m): return None
    if oc[i]==-1 and oc[i-1]!=1: return None   # solo dopo stato bull
    if r>55 and a>=18 and m<0: return 'sell'
    return None

def v8_sell_strong_trend(ind, i):
    """
    V8 — SELL ONLY ALTA QUALITÀ: ADX forte + DI- domina + OBV bear + RSI 50-70
    Confluenza massima: trend ribassista forte (ADX+DI-) confermato da OBV.
    RSI non ancora oversold (c'è ancora spazio per scendere).
    """
    if i<2: return None
    oc=ind['obv_oc']; r=ind['rsi'][i]; a=ind['adx'][i]
    dip=ind['dip'][i]; dim=ind['dim'][i]; m=ind['mom10'][i]; mc=ind['macd'][i]
    if None in (r,a,dip,dim,m,mc): return None
    if oc[i]==-1 and a>=25 and dim>dip and r>42 and r<72 and m<0: return 'sell'
    return None

VARIANTS = {
    'V1_Flip_RSI_Mom_ADX':    v1_flip_rsi_mom,
    'V2_Triple_MACD_ADX':     v2_triple_align_adx,
    'V3_Flip_Extreme_ADX':    v3_flip_rsi_extreme_adx,
    'V4_SELL_Exhaustion':     v4_sell_exhaustion_obv,
    'V5_Mom_Session':         v5_momentum_session,
    'V6_Strong_5cond':        v6_strong_signal,
    'V7_SELL_Flip_RSI_MACD':  v7_sell_flip_rsi_macd,
    'V8_SELL_Strong_Trend':   v8_sell_strong_trend,
}

# ─────────────────────────────────────────────────────────────────────────────
# BACKTEST ENGINE
# ─────────────────────────────────────────────────────────────────────────────
def run_backtest(candles, ind, fn, tf_name='H1'):
    cfg     = TF_CONFIG.get(tf_name, TF_CONFIG['H1'])
    sess_s, sess_e = cfg['session']
    cool    = cfg['cooldown_bars']
    n       = len(candles)
    warmup  = max(80, int(n*0.05))  # almeno 5% per warmup indicatori

    trades  = []; day_n=defaultdict(int); last_bar=defaultdict(lambda:-999)
    for i in range(warmup, n-1):
        c  = candles[i]; ts = c['t']
        dt = datetime.datetime.utcfromtimestamp(ts)
        hour = dt.hour; day = dt.strftime('%Y-%m-%d')

        # Filtri universali
        if not (sess_s <= hour < sess_e): continue
        av = ind['atr'][i]; aa = ind['atr30'][i]
        if av and aa and av > EXTREME_K*aa: continue
        if day_n[day] >= MAX_TRADES: continue
        if i - last_bar[day] < cool: continue

        # Filtro sessione specifico per V5
        if fn.__name__ == 'v5_momentum_session' and not (7<=hour<17): continue

        sig = fn(ind, i)
        if sig is None: continue

        entry = c['c']
        atr_v = av or 10
        tp_pts = atr_v * TP_ATR_MULT
        sl_pts = atr_v * SL_ATR_MULT
        tp_p = entry+tp_pts if sig=='buy' else entry-tp_pts
        sl_p = entry-sl_pts if sig=='buy' else entry+sl_pts
        spread = atr_v * 0.05  # 5% ATR come spread realistico

        outcome = 'open'; close_price = entry
        for j in range(i+1, min(i+50, n)):
            jh=candles[j]['h']; jl=candles[j]['l']
            if sig=='buy':
                if jh>=tp_p: outcome='win'; close_price=tp_p; break
                if jl<=sl_p: outcome='loss'; close_price=sl_p; break
            else:
                if jl<=tp_p: outcome='win'; close_price=tp_p; break
                if jh>=sl_p: outcome='loss'; close_price=sl_p; break
        if outcome=='open': continue

        win = outcome=='win'
        pnl = (close_price-entry if sig=='buy' else entry-close_price) - spread
        trades.append({'date':day,'hour':hour,'dir':sig,'entry':entry,
                       'outcome':outcome,'pnl':round(pnl,3)})
        day_n[day]+=1; last_bar[day]=i
    return trades

def calc_stats(trades):
    if not trades: return None
    wins  = [t for t in trades if t['outcome']=='win']
    loss  = [t for t in trades if t['outcome']=='loss']
    n     = len(trades)
    wr    = len(wins)/n*100
    pnl   = sum(t['pnl'] for t in trades)
    gw    = sum(t['pnl'] for t in wins)  if wins  else 0
    gl    = abs(sum(t['pnl'] for t in loss)) if loss else 0.001
    pf    = round(gw/gl,3)
    days  = set(t['date'] for t in trades)
    avg_d = pnl/len(days) if days else 0

    # Max Drawdown
    cum=0; peak=0; dd=0
    for t in sorted(trades, key=lambda x: x['date']+f"{x['hour']:02d}"):
        cum+=t['pnl']
        if cum>peak: peak=cum
        if peak-cum>dd: dd=peak-cum

    # Monthly
    mo = defaultdict(list)
    for t in trades: mo[t['date'][:7]].append(t['pnl'])
    pos_mo = sum(1 for v in mo.values() if sum(v)>0)

    # Buy/Sell breakdown
    buys  = [t for t in trades if t['dir']=='buy']
    sells = [t for t in trades if t['dir']=='sell']
    buy_wr  = len([t for t in buys  if t['outcome']=='win'])/len(buys)*100  if buys  else 0
    sell_wr = len([t for t in sells if t['outcome']=='win'])/len(sells)*100 if sells else 0

    return {
        'n': n, 'wr': round(wr,1), 'pnl': round(pnl,1), 'pf': pf,
        'dd': round(dd,1), 'avg_day': round(avg_d,2),
        'pos_months': f"{pos_mo}/{len(mo)}",
        'n_buy': len(buys), 'n_sell': len(sells),
        'buy_wr': round(buy_wr,1), 'sell_wr': round(sell_wr,1),
    }

# ─────────────────────────────────────────────────────────────────────────────
# MT5 FETCH
# ─────────────────────────────────────────────────────────────────────────────
def fetch_from_mt5(tf_name):
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("  SKIP (MetaTrader5 non installato)")
        return None

    tf_map = {
        'M15': mt5.TIMEFRAME_M15,
        'M30': mt5.TIMEFRAME_M30,
        'H1':  mt5.TIMEFRAME_H1,
        'H4':  mt5.TIMEFRAME_H4,
        'D1':  mt5.TIMEFRAME_D1,
    }
    if tf_name not in tf_map:
        return None

    if not mt5.initialize():
        print(f"  ERRORE mt5.initialize(): {mt5.last_error()}")
        return None

    mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER)

    sym = None
    for s in SYMBOL_CANDIDATES:
        info = mt5.symbol_info(s)
        if info and info.visible: sym=s; break
        if info: mt5.symbol_select(s,True); info=mt5.symbol_info(s)
        if info and info.visible: sym=s; break
    if not sym:
        print("  ERRORE: simbolo GOLD non trovato")
        mt5.shutdown(); return None

    date_to   = datetime.datetime.now(datetime.timezone.utc)
    date_from = date_to - datetime.timedelta(days=DAYS+5)
    rates = mt5.copy_rates_range(sym, tf_map[tf_name], date_from, date_to)
    mt5.shutdown()

    if rates is None or len(rates)==0:
        print(f"  ERRORE: nessuna candela per {tf_name}")
        return None

    cutoff = (date_to - datetime.timedelta(days=DAYS)).timestamp()
    candles=[]
    for r in rates:
        if float(r['time'])<cutoff: continue
        c=float(r['close'])
        if math.isnan(c) or c<=0: continue
        candles.append({'t':int(r['time']),'o':float(r['open']),
                        'h':float(r['high']),'l':float(r['low']),
                        'c':c,'v':float(r.get('tick_volume',0) or 0)})
    print(f"  {len(candles)} candele {tf_name} da MT5 ({sym})")
    return candles

def load_json(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    candles = d['candles'] if isinstance(d,dict) and 'candles' in d else d
    print(f"  {len(candles)} candele da {path}")
    return candles

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    print("="*72)
    print("TradeFlow AI — Backtest OBV MACD + RSI + Momentum")
    print("6 varianti strategiche × multi-timeframe × 2 anni XAU/USD")
    print("="*72)

    # Raccolta dati per timeframe
    datasets = {}

    # H1 (può venire da file o MT5)
    print("\nCaricamento dati...")
    if args.h1_file:
        c = load_json(args.h1_file)
        if c: datasets['H1'] = c
    if 'H1' not in datasets and args.mt5:
        print("  Fetching H1 da MT5...")
        c = fetch_from_mt5('H1')
        if c: datasets['H1'] = c

    if args.mt5:
        for tf in ['M15','M30','H4','D1']:
            print(f"  Fetching {tf} da MT5...")
            c = fetch_from_mt5(tf)
            if c: datasets[tf] = c
    else:
        file_map = {'M15': args.m15_file, 'M30': args.m30_file,
                    'H4': args.h4_file, 'D1': args.d1_file}
        for tf, path in file_map.items():
            if path:
                c = load_json(path)
                if c: datasets[tf] = c

    if not datasets:
        print("\nERRORE: nessun dato disponibile.")
        print("Usa --h1-file xauusd_h1_730d.json oppure --mt5")
        sys.exit(1)

    print(f"\nTimeframe caricati: {list(datasets.keys())}")

    # ── BACKTEST ─────────────────────────────────────────────────────────────
    all_results = {}  # {tf: {variant: stats}}

    for tf, candles in sorted(datasets.items()):
        cfg = TF_CONFIG.get(tf, TF_CONFIG['H1'])
        first = datetime.datetime.fromtimestamp(candles[0]['t']).strftime('%Y-%m-%d')
        last  = datetime.datetime.fromtimestamp(candles[-1]['t']).strftime('%Y-%m-%d')
        print(f"\n{'='*72}")
        print(f"TIMEFRAME: {tf}  |  {len(candles)} candele  |  {first} → {last}")
        print('='*72)
        print(f"{'Variante':<26} {'N':>5} {'WR':>6} {'P&L':>9} {'PF':>6} {'DD':>8} {'Mesi+':>7} {'BuyWR':>6} {'SelWR':>6}")
        print('-'*72)

        ind = compute(candles)
        tf_results = {}

        for vname, vfn in VARIANTS.items():
            trades = run_backtest(candles, ind, vfn, tf)
            s = calc_stats(trades)
            tf_results[vname] = {'stats': s, 'trades_count': len(trades) if trades else 0}
            if s and s['n'] >= cfg['min_trades']:
                status = '✅' if s['pf']>=1.5 and s['wr']>=55 else ('⚠️' if s['pf']>=1.1 else '❌')
                print(f"{status} {vname:<24} {s['n']:>5} {s['wr']:>5.1f}% {s['pnl']:>9.1f} {s['pf']:>6.3f} {s['dd']:>8.1f} {s['pos_months']:>7} {s['buy_wr']:>5.1f}% {s['sell_wr']:>5.1f}%")
            elif s:
                print(f"⚫ {vname:<24} {s['n']:>5} {s['wr']:>5.1f}% {s['pnl']:>9.1f} {s['pf']:>6.3f} {s['dd']:>8.1f} {s['pos_months']:>7}  (N<{cfg['min_trades']}→skip)")
            else:
                print(f"── {vname:<24}     0  (nessun trade)")

        all_results[tf] = tf_results

    # ── RANKING GLOBALE ───────────────────────────────────────────────────────
    print(f"\n{'='*72}")
    print("RANKING GLOBALE — Top 10 combinazioni TF × Variante")
    print(f"{'='*72}")
    print(f"{'Rank':<5} {'TF':<5} {'Variante':<26} {'N':>5} {'WR':>6} {'PF':>6} {'P&L':>9} {'DD':>8} {'Score':>7}")
    print('-'*72)

    ranking = []
    for tf, tf_res in all_results.items():
        cfg = TF_CONFIG.get(tf, TF_CONFIG['H1'])
        for vname, res in tf_res.items():
            s = res['stats']
            if s and s['n'] >= cfg['min_trades'] and s['pf']>=1.0:
                # Score composito: bilancia PF, WR, N trade, P&L/DD
                rr = s['pnl'] / s['dd'] if s['dd']>0 else s['pnl']
                score = s['pf'] * (s['wr']/100) * math.log(s['n']+1) * min(rr/2, 1.5)
                ranking.append({'tf':tf,'variant':vname,'stats':s,'score':round(score,3)})

    ranking.sort(key=lambda x: -x['score'])
    top10 = ranking[:10]
    for k, r in enumerate(top10, 1):
        s = r['stats']
        print(f"#{k:<4} {r['tf']:<5} {r['variant']:<26} {s['n']:>5} {s['wr']:>5.1f}% {s['pf']:>6.3f} {s['pnl']:>9.1f} {s['dd']:>8.1f} {r['score']:>7.3f}")

    # ── RACCOMANDAZIONE ───────────────────────────────────────────────────────
    print(f"\n{'='*72}")
    print("RACCOMANDAZIONE per strategy.js")
    print('='*72)

    # Best per ogni TF
    best_per_tf = {}
    for tf in all_results:
        cfg = TF_CONFIG.get(tf, TF_CONFIG['H1'])
        tf_cands = [(v,r) for v,r in all_results[tf].items()
                    if r['stats'] and r['stats']['n']>=cfg['min_trades'] and r['stats']['pf']>=1.3]
        if tf_cands:
            best = max(tf_cands, key=lambda x: x[1]['stats']['pf'])
            best_per_tf[tf] = best

    if not best_per_tf:
        print("  Nessuna variante con PF>=1.3 su N>=min. Abbassa le soglie o usa più dati.")
    else:
        for tf,(vname,res) in best_per_tf.items():
            s=res['stats']
            print(f"\n  {tf}: {vname}")
            print(f"    WR={s['wr']}% | PF={s['pf']} | P&L=${s['pnl']} | MaxDD=${s['dd']}")
            print(f"    N={s['n']} trade | Mesi pos: {s['pos_months']}")
            print(f"    BUY WR={s['buy_wr']}% | SELL WR={s['sell_wr']}%")

    # ── SAVE JSON ─────────────────────────────────────────────────────────────
    out = {
        'generated': datetime.datetime.utcnow().isoformat(),
        'config': {'tp_mult': TP_ATR_MULT, 'sl_mult': SL_ATR_MULT, 'days': DAYS},
        'results': {
            tf: {
                vname: {
                    'stats': res['stats'],
                    'trades_count': res['trades_count'],
                }
                for vname, res in tf_res.items()
            }
            for tf, tf_res in all_results.items()
        },
        'ranking': [
            {'rank':k+1,'tf':r['tf'],'variant':r['variant'],'score':r['score'],'stats':r['stats']}
            for k,r in enumerate(ranking[:20])
        ],
        'best_per_tf': {
            tf: {'variant':vname,'stats':res['stats']}
            for tf,(vname,res) in best_per_tf.items()
        }
    }
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nRisultati salvati in: {args.out}")
    print(f"\nProssimo step:")
    print(f"  1. Fetch dati multi-TF da MT5:")
    print(f"     python scripts/fetch_mt5_history.py --tf M15 --out xauusd_m15_mt5.json")
    print(f"     python scripts/fetch_mt5_history.py --tf H4  --out xauusd_h4_mt5.json")
    print(f"     python scripts/fetch_mt5_history.py --tf D1  --out xauusd_d1_mt5.json")
    print(f"  2. Riesegui con MT5:")
    print(f"     python scripts/backtest_obv_rsi_mom.py --mt5")

if __name__ == '__main__':
    main()
