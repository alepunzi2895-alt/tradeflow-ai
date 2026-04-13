#!/usr/bin/env python3
"""
TradeFlow AI — Strategy Engine
Backtesta 7 strategie su 730gg H1 XAU/USD, rileva regime di mercato giornaliero
e determina la strategia ottimale per ogni regime.
Output: strategy_engine_results.json con mappatura regime→strategia + P&L completo.

MAX 3 trade/giorno, cooldown 60 min, skip giorni estremi (ATR > 3x media 30gg)
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import json, datetime, math
import urllib.request
from collections import defaultdict
try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False

# ── CONFIG ────────────────────────────────────────────────────────────────────
SYMBOL     = 'GC=F'   # Gold Futures — stessi pattern, dati disponibili 2 anni H1
INTERVAL   = '1h'
RANGE_DAYS = 730
TP_USD     = 20.0
SL_USD     = 12.0
MAX_TRADES_DAY = 3
COOLDOWN_H     = 1        # ore minime tra trade (stesso giorno)
EXTREME_DAY_MULT = 3.0    # ATR > 3x media 30gg = giorno estremo, skip
SESSION_START = 7         # UTC ora inizio sessione valida (London open)
SESSION_END   = 17        # UTC ora fine sessione valida (NY close)

# ── DOWNLOAD ─────────────────────────────────────────────────────────────────
def download_candles():
    if not HAS_YF:
        raise RuntimeError("yfinance non installato. Esegui: pip install yfinance")
    print(f"  Scarico {SYMBOL} H1 2 anni via yfinance...")
    df = yf.download(SYMBOL, period=f'{RANGE_DAYS}d', interval='1h', progress=False)
    if df is None or len(df) == 0:
        raise RuntimeError(f"Nessun dato per {SYMBOL}")
    # Flatten multi-level columns se presenti
    if hasattr(df.columns, 'levels'):
        df.columns = df.columns.get_level_values(0)
    candles = []
    for ts, row in df.iterrows():
        t = int(ts.timestamp())
        o = row.get('Open',None); h = row.get('High',None)
        l = row.get('Low',None);  c = row.get('Close',None)
        v = row.get('Volume', 0)
        if None in (o,h,l,c) or math.isnan(float(c)): continue
        candles.append({'t':t,'o':float(o),'h':float(h),'l':float(l),'c':float(c),'v':float(v or 0)})
    return candles

# ── MATH HELPERS ──────────────────────────────────────────────────────────────
def ema(src, p):
    k = 2/(p+1); v = src[0]; out = [v]
    for x in src[1:]: v = x*k + v*(1-k); out.append(v)
    return out

def sma(src, p):
    out = [None]*(p-1)
    for i in range(p-1, len(src)):
        out.append(sum(src[i-p+1:i+1])/p)
    return out

def rsi(src, p=14):
    """RSI Wilder smoothing — output stesso len di src"""
    n = len(src)
    out = [None]*n
    gains = [max(0, src[i]-src[i-1]) for i in range(1,n)]
    losses = [max(0, src[i-1]-src[i]) for i in range(1,n)]
    if len(gains) < p: return out
    ag = sum(gains[:p])/p; al = sum(losses[:p])/p
    # indice p in src corrisponde a gains[p-1]
    out[p] = 100 - 100/(1+(ag/al if al>0 else 100))
    for i in range(p, len(gains)):
        ag = (ag*(p-1)+gains[i])/p
        al = (al*(p-1)+losses[i])/p
        out[i+1] = 100 - 100/(1+(ag/al if al>0 else 100))
    return out

def bollinger(src, p=20, mult=2.0):
    mid = sma(src, p)
    upper, lower = [], []
    for i in range(len(src)):
        if mid[i] is None: upper.append(None); lower.append(None); continue
        sl = src[i-p+1:i+1]
        std = math.sqrt(sum((x-mid[i])**2 for x in sl)/p)
        upper.append(mid[i]+mult*std)
        lower.append(mid[i]-mult*std)
    return upper, mid, lower

def stochastic(high, low, close, kp=14, dp=3, sp=3):
    """Stochastic %K smooth, %D smooth"""
    raw_k = [None]*(kp-1)
    for i in range(kp-1, len(close)):
        h = max(high[i-kp+1:i+1]); l = min(low[i-kp+1:i+1])
        raw_k.append((close[i]-l)/(h-l)*100 if h>l else 50)
    # smooth K with dp-period SMA
    sk = sma([x if x is not None else 50 for x in raw_k], dp)
    # smooth D with sp-period SMA
    sd = sma([x if x is not None else 50 for x in sk], sp)
    return sk, sd

def atr(high, low, close, p=14):
    tr = [0]
    for i in range(1, len(close)):
        tr.append(max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1])))
    return sma(tr, p)

def adx_calc(high, low, close, p=14):
    n = len(close)
    TR = [0]; DMP = [0]; DMM = [0]
    for i in range(1, n):
        TR.append(max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1])))
        up = high[i]-high[i-1]; dn = low[i-1]-low[i]
        DMP.append(up if up>dn and up>0 else 0)
        DMM.append(dn if dn>up and dn>0 else 0)
    # Wilder smooth
    sTR=[0]; sDMP=[0]; sDMM=[0]
    for i in range(1,n):
        sTR.append(sTR[-1]-sTR[-1]/p+TR[i])
        sDMP.append(sDMP[-1]-sDMP[-1]/p+DMP[i])
        sDMM.append(sDMM[-1]-sDMM[-1]/p+DMM[i])
    DIP=[sDMP[i]/sTR[i]*100 if sTR[i]>0 else 0 for i in range(n)]
    DIM=[sDMM[i]/sTR[i]*100 if sTR[i]>0 else 0 for i in range(n)]
    DX=[abs(DIP[i]-DIM[i])/(DIP[i]+DIM[i])*100 if (DIP[i]+DIM[i])>0 else 0 for i in range(n)]
    ADX_v = sma(DX, p)
    return ADX_v, DIP, DIM

def compute_indicators(candles):
    H=[c['h'] for c in candles]
    L=[c['l'] for c in candles]
    C=[c['c'] for c in candles]
    O=[c['o'] for c in candles]
    n=len(C)

    e12=ema(C,12); e26=ema(C,26)
    macd_line=[e12[i]-e26[i] for i in range(n)]
    macd_sig=ema(macd_line,9)
    macd_hist=[macd_line[i]-macd_sig[i] for i in range(n)]

    adx_v, dip, dim = adx_calc(H, L, C, 14)
    atr_v = atr(H, L, C, 14)
    rsi_v = rsi(C, 14)
    bb_up, bb_mid, bb_lo = bollinger(C, 20, 2.0)
    sk, sd = stochastic(H, L, C, 14, 3, 3)

    e20  = ema(C, 20)
    e50  = ema(C, 50)
    e200 = ema(C, 200)

    # ATR 30-period SMA for extreme day detection
    atr_avg30 = sma([x if x else 0 for x in atr_v], 30)

    # BB width normalized
    bb_width = [
        (bb_up[i]-bb_lo[i])/bb_mid[i] if (bb_mid[i] and bb_up[i] and bb_lo[i]) else None
        for i in range(n)
    ]
    bb_width_avg = sma([x if x else 0 for x in bb_width], 20)

    return {
        'H':H,'L':L,'C':C,'O':O,'n':n,
        'macd':macd_line,'macd_sig':macd_sig,'macd_hist':macd_hist,
        'adx':adx_v,'dip':dip,'dim':dim,
        'atr':atr_v,'atr_avg30':atr_avg30,
        'rsi':rsi_v,
        'bb_up':bb_up,'bb_mid':bb_mid,'bb_lo':bb_lo,
        'bb_width':bb_width,'bb_width_avg':bb_width_avg,
        'stk':sk,'std':sd,
        'ema20':e20,'ema50':e50,'ema200':e200,
    }

# ── REGIME DETECTION ─────────────────────────────────────────────────────────
def detect_regime(inds, i):
    """Rileva il regime di mercato all'inizio del giorno (usa dati di ieri)"""
    adx = inds['adx'][i]
    dip = inds['dip'][i]
    dim = inds['dim'][i]
    atr_v = inds['atr'][i]
    atr_a = inds['atr_avg30'][i]
    e20 = inds['ema20'][i]
    e50 = inds['ema50'][i]
    e200 = inds['ema200'][i]
    rsi_v = inds['rsi'][i]

    if None in (adx, atr_v, atr_a, e20, e50, e200): return 'UNKNOWN'
    if atr_a and atr_v: rel_vol = atr_v / atr_a
    else: rel_vol = 1.0

    trend_up   = e20 > e50 > e200
    trend_down = e20 < e50 < e200

    if adx >= 30 and dip > dim:
        return 'TREND_UP'
    elif adx >= 30 and dim > dip:
        return 'TREND_DOWN'
    elif adx >= 22:
        if dip > dim: return 'WEAK_TREND_UP'
        else: return 'WEAK_TREND_DOWN'
    elif rel_vol > 1.4:
        return 'VOLATILE_RANGE'
    else:
        return 'RANGE'

# ── STRATEGY SIGNAL GENERATORS ───────────────────────────────────────────────
# Ogni strategia restituisce: 'buy', 'sell', o None

def strat_exhaustion(inds, i):
    """EXHAUSTION: ADX forte + MACD contro-trend (HIGH-WR pattern 82-95%)"""
    adx=inds['adx'][i]; dip=inds['dip'][i]; dim=inds['dim'][i]
    macd=inds['macd'][i]; sig=inds['macd_sig'][i]
    if None in (adx,dip,dim,macd,sig): return None
    diff = macd - sig
    hour = datetime.datetime.utcfromtimestamp(inds['C'][i] if False else 0)  # placeholder
    # SELL: ADX≥30 + DI- dominante + MACD bullish esteso (esaurimento rialzo)
    if adx>=30 and dim>dip and abs(dim-dip)>=15 and diff>=1.0:
        return 'sell'
    # BUY: ADX≥30 + DI+ dominante + MACD bearish esteso (esaurimento ribasso)
    if adx>=28 and dip>dim and abs(dip-dim)>=15 and diff<=-1.0:
        return 'buy'
    return None

def strat_ema_trend(inds, i):
    """EMA_TREND: Pullback su EMA20 in trend forte (EMA20>EMA50>EMA200)"""
    e20=inds['ema20'][i]; e50=inds['ema50'][i]; e200=inds['ema200'][i]
    c=inds['C'][i]; adx=inds['adx'][i]; rsi_v=inds['rsi'][i]
    if None in (e20,e50,e200,adx,rsi_v): return None
    # BUY: trend rialzista + prezzo tra EMA20 e EMA50 (pullback) + ADX valido
    if e20>e50>e200 and adx>=20:
        if e50 <= c <= e20*1.002 and 35<=rsi_v<=60:
            return 'buy'
    # SELL: trend ribassista + prezzo tra EMA20 e EMA50 (pullback) + ADX valido
    if e20<e50<e200 and adx>=20:
        if e20*0.998 <= c <= e50 and 40<=rsi_v<=65:
            return 'sell'
    return None

def strat_rsi_extreme(inds, i):
    """RSI_EXTREME: RSI in zone estreme + ADX basso (ranging)"""
    rsi_v=inds['rsi'][i]; adx=inds['adx'][i]
    bb_up=inds['bb_up'][i]; bb_lo=inds['bb_lo'][i]; c=inds['C'][i]
    if None in (rsi_v,adx,bb_up,bb_lo): return None
    if adx>=28: return None  # solo in ranging
    # BUY: RSI oversold + prezzo vicino a BB inferiore
    if rsi_v<=32 and c<=bb_lo*1.003:
        return 'buy'
    # SELL: RSI overbought + prezzo vicino a BB superiore
    if rsi_v>=68 and c>=bb_up*0.997:
        return 'sell'
    return None

def strat_bollinger_reversal(inds, i):
    """BB_REVERSAL: Tocco banda esterna + conferma RSI + ADX basso/medio"""
    bb_up=inds['bb_up'][i]; bb_lo=inds['bb_lo'][i]
    bb_mid=inds['bb_mid'][i]; c=inds['C'][i]
    rsi_v=inds['rsi'][i]; adx=inds['adx'][i]
    if None in (bb_up,bb_lo,bb_mid,rsi_v,adx): return None
    # Compra rimbalzo su banda inferiore
    if c<=bb_lo*1.001 and rsi_v<=45 and adx<30:
        return 'buy'
    # Vendi rimbalzo su banda superiore
    if c>=bb_up*0.999 and rsi_v>=55 and adx<30:
        return 'sell'
    return None

def strat_stoch_cross(inds, i):
    """STOCH_CROSS: Stochastic K crosses D in zone estreme"""
    sk=inds['stk']; sd=inds['std']
    if i<1 or sk[i] is None or sd[i] is None: return None
    if sk[i-1] is None or sd[i-1] is None: return None
    adx=inds['adx'][i]
    if adx is None or adx>=30: return None  # solo ranging/weak
    # Cross rialzista in zona oversold (<25)
    if sk[i-1]<=sd[i-1] and sk[i]>sd[i] and sk[i]<30:
        return 'buy'
    # Cross ribassista in zona overbought (>75)
    if sk[i-1]>=sd[i-1] and sk[i]<sd[i] and sk[i]>70:
        return 'sell'
    return None

def strat_macd_zero_cross(inds, i):
    """MACD_ZERO: MACD histogram incrocia lo zero + ADX moderato + EMA allineate"""
    mh=inds['macd_hist']; e20=inds['ema20'][i]; e50=inds['ema50'][i]
    adx=inds['adx'][i]; rsi_v=inds['rsi'][i]; c=inds['C'][i]
    if i<1 or None in (e20,e50,adx,rsi_v): return None
    if mh[i-1] is None or mh[i] is None: return None
    # Cross rialzista (hist da neg a pos) + EMA20>EMA50 + RSI in zona giusta
    if mh[i-1]<0 and mh[i]>0 and e20>e50 and 40<=rsi_v<=65:
        return 'buy'
    # Cross ribassista (hist da pos a neg) + EMA20<EMA50 + RSI in zona giusta
    if mh[i-1]>0 and mh[i]<0 and e20<e50 and 35<=rsi_v<=60:
        return 'sell'
    return None

def strat_session_momentum(inds, i, hour):
    """SESSION_MOM: Momentum nelle prime ore di London/NY — segue la direzione del momentum"""
    if not (7 <= hour <= 10): return None  # solo apertura London
    macd=inds['macd'][i]; sig=inds['macd_sig'][i]
    rsi_v=inds['rsi'][i]; adx=inds['adx'][i]; e50=inds['ema50'][i]; c=inds['C'][i]
    if None in (macd,sig,rsi_v,adx,e50): return None
    diff = macd - sig
    # BUY: MACD bullish + RSI momentum + EMA50 supporto
    if diff>0.3 and rsi_v>=50 and c>e50*0.999 and adx>=15:
        return 'buy'
    # SELL: MACD bearish + RSI momentum + EMA50 resistenza
    if diff<-0.3 and rsi_v<=50 and c<e50*1.001 and adx>=15:
        return 'sell'
    return None

STRATEGIES = {
    'EXHAUSTION':       strat_exhaustion,
    'EMA_TREND':        strat_ema_trend,
    'RSI_EXTREME':      strat_rsi_extreme,
    'BB_REVERSAL':      strat_bollinger_reversal,
    'STOCH_CROSS':      strat_stoch_cross,
    'MACD_ZERO':        strat_macd_zero_cross,
    'SESSION_MOM':      lambda inds,i: None,  # requires hour, handled specially
}

# ── REGIME → STRATEGIE CONSIGLIATE ───────────────────────────────────────────
REGIME_STRATEGY_CANDIDATES = {
    'TREND_UP':       ['EXHAUSTION','EMA_TREND','SESSION_MOM','MACD_ZERO'],
    'TREND_DOWN':     ['EXHAUSTION','EMA_TREND','SESSION_MOM','MACD_ZERO'],
    'WEAK_TREND_UP':  ['EMA_TREND','MACD_ZERO','STOCH_CROSS','SESSION_MOM'],
    'WEAK_TREND_DOWN':['EMA_TREND','MACD_ZERO','STOCH_CROSS','SESSION_MOM'],
    'VOLATILE_RANGE': ['RSI_EXTREME','BB_REVERSAL','STOCH_CROSS','SESSION_MOM'],
    'RANGE':          ['RSI_EXTREME','BB_REVERSAL','STOCH_CROSS','MACD_ZERO'],
    'UNKNOWN':        ['EMA_TREND','RSI_EXTREME','MACD_ZERO'],
}

# ── BACKTEST SINGOLA STRATEGIA ────────────────────────────────────────────────
def run_strategy_backtest(candles, inds, strategy_name, tp=TP_USD, sl=SL_USD):
    """Simula una singola strategia su tutte le candele. Max 3 trade/gg, cooldown 1h."""
    trades = []
    n = len(candles)
    day_trades = defaultdict(int)    # data → count
    day_last_trade_h = defaultdict(lambda: -99)  # data → last trade hour

    strategy_fn = STRATEGIES[strategy_name]

    for i in range(210, n):  # warmup 210 candele per EMA200
        c = candles[i]
        ts = c['t']
        dt = datetime.datetime.utcfromtimestamp(ts)
        hour = dt.hour
        day_key = dt.strftime('%Y-%m-%d')

        # Sessione valida
        if not (SESSION_START <= hour < SESSION_END): continue

        # Extreme day: ATR > 3x media 30gg
        atr_v = inds['atr'][i]; atr_a = inds['atr_avg30'][i]
        if atr_v and atr_a and atr_v > EXTREME_DAY_MULT * atr_a: continue

        # Max trade per giorno
        if day_trades[day_key] >= MAX_TRADES_DAY: continue

        # Cooldown
        if hour - day_last_trade_h[day_key] < COOLDOWN_H: continue

        # Genera segnale
        if strategy_name == 'SESSION_MOM':
            sig = strat_session_momentum(inds, i, hour)
        else:
            sig = strategy_fn(inds, i)
        if sig is None: continue

        # Simula trade
        entry = c['c']
        tp_price = entry + tp if sig=='buy' else entry - tp
        sl_price = entry - sl if sig=='buy' else entry + sl
        outcome = 'open'
        win = False

        for j in range(i+1, min(i+25, n)):  # max 24h lookahead
            jh = candles[j]['h']; jl = candles[j]['l']
            if sig=='buy':
                if jh >= tp_price: outcome='win'; win=True; break
                if jl <= sl_price: outcome='loss'; break
            else:
                if jl <= tp_price: outcome='win'; win=True; break
                if jh >= sl_price: outcome='loss'; break

        if outcome=='open': continue  # trade non chiuso in 24h, skip

        pnl = tp if win else -sl
        trades.append({'date':day_key,'hour':hour,'dir':sig,'entry':entry,
                        'outcome':outcome,'pnl':pnl,'strategy':strategy_name})
        day_trades[day_key] += 1
        day_last_trade_h[day_key] = hour

    return trades

# ── BACKTEST CON REGIME SELECTION ─────────────────────────────────────────────
def run_regime_backtest(candles, inds):
    """Ogni giorno seleziona le migliori 2 strategie per il regime rilevato."""
    n = len(candles)

    # Pre-calcola regime per ogni giorno (usa indicatori alle 6 UTC = apertura giorno)
    day_regimes = {}
    for i in range(210, n):
        c = candles[i]
        dt = datetime.datetime.utcfromtimestamp(c['t'])
        day_key = dt.strftime('%Y-%m-%d')
        if dt.hour == 7 and day_key not in day_regimes:
            day_regimes[day_key] = detect_regime(inds, i)

    trades = []
    day_trades_count = defaultdict(int)
    day_last_h = defaultdict(lambda: -99)

    for i in range(210, n):
        c = candles[i]
        ts = c['t']
        dt = datetime.datetime.utcfromtimestamp(ts)
        hour = dt.hour
        day_key = dt.strftime('%Y-%m-%d')

        if not (SESSION_START <= hour < SESSION_END): continue

        atr_v = inds['atr'][i]; atr_a = inds['atr_avg30'][i]
        if atr_v and atr_a and atr_v > EXTREME_DAY_MULT * atr_a: continue
        if day_trades_count[day_key] >= MAX_TRADES_DAY: continue
        if hour - day_last_h[day_key] < COOLDOWN_H: continue

        regime = day_regimes.get(day_key, 'UNKNOWN')
        strategy_pool = REGIME_STRATEGY_CANDIDATES.get(regime, list(STRATEGIES.keys()))

        # Prova strategie nell'ordine del pool, prendi il primo segnale valido
        sig = None; chosen_strat = None
        for strat_name in strategy_pool:
            if strat_name == 'SESSION_MOM':
                s = strat_session_momentum(inds, i, hour)
            else:
                s = STRATEGIES[strat_name](inds, i)
            if s is not None:
                sig = s; chosen_strat = strat_name; break

        if sig is None: continue

        entry = c['c']
        tp_price = entry + TP_USD if sig=='buy' else entry - TP_USD
        sl_price = entry - SL_USD if sig=='buy' else entry + SL_USD
        outcome = 'open'; win = False

        for j in range(i+1, min(i+25, n)):
            jh = candles[j]['h']; jl = candles[j]['l']
            if sig=='buy':
                if jh>=tp_price: outcome='win'; win=True; break
                if jl<=sl_price: outcome='loss'; break
            else:
                if jl<=tp_price: outcome='win'; win=True; break
                if jh>=sl_price: outcome='loss'; break

        if outcome=='open': continue
        pnl = TP_USD if win else -SL_USD
        trades.append({
            'date':day_key,'hour':hour,'dir':sig,'entry':entry,
            'outcome':outcome,'pnl':pnl,'strategy':chosen_strat,'regime':regime
        })
        day_trades_count[day_key] += 1
        day_last_h[day_key] = hour

    return trades

# ── STATISTICHE ───────────────────────────────────────────────────────────────
def stats(trades):
    if not trades: return {'n':0,'wr':0,'pnl':0,'pf':0,'avg_per_day':0,'trades_per_day':0}
    wins = [t for t in trades if t['outcome']=='win']
    losses = [t for t in trades if t['outcome']=='loss']
    n = len(trades)
    wr = len(wins)/n*100
    pnl = sum(t['pnl'] for t in trades)
    gross_win = sum(t['pnl'] for t in wins) if wins else 0
    gross_loss = abs(sum(t['pnl'] for t in losses)) if losses else 0.001
    pf = gross_win/gross_loss

    days = set(t['date'] for t in trades)
    avg_pday = pnl/len(days) if days else 0
    trades_pday = n/len(days) if days else 0

    # Monthly breakdown
    monthly = defaultdict(list)
    for t in trades: monthly[t['date'][:7]].append(t['pnl'])
    pos_months = sum(1 for v in monthly.values() if sum(v)>0)

    # Max drawdown
    cum = 0; peak = 0; dd = 0
    for t in sorted(trades, key=lambda x:x['date']+str(x['hour'])):
        cum += t['pnl']
        if cum > peak: peak = cum
        if peak - cum > dd: dd = peak - cum

    return {
        'n':n,'wr':round(wr,1),'pnl':round(pnl,1),'pf':round(pf,3),
        'avg_per_day':round(avg_pday,2),'trades_per_day':round(trades_pday,2),
        'pos_months':f'{pos_months}/{len(monthly)}','max_dd':round(dd,1)
    }

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    print("TradeFlow AI — Strategy Engine (7 strategie + regime detection)")
    print("="*65)

    print("Download candele XAU/USD H1 (730gg)...")
    candles = download_candles()
    print(f"  {len(candles)} candele")

    print("Calcolo indicatori (MACD, ADX, RSI, BB, Stoch, EMA20/50/200)...")
    inds = compute_indicators(candles)

    # ── 1. Backtest individuale ogni strategia ────────────────────────────────
    print("\n" + "="*65)
    print("FASE 1: Backtest individuale — tutte le 7 strategie")
    print("="*65)
    strategy_results = {}
    fmt_hdr = f"{'Strategia':<20} {'N':>5} {'WR%':>6} {'P&L':>8} {'PF':>6} {'$/gg':>7} {'tr/gg':>6} {'Mesi+':>7} {'DD':>7}"
    print(fmt_hdr)
    print("-"*65)

    all_strategies = list(STRATEGIES.keys())
    for name in all_strategies:
        trades = run_strategy_backtest(candles, inds, name)
        s = stats(trades)
        strategy_results[name] = {'stats':s,'trades':trades}
        print(f"{name:<20} {s['n']:>5} {s['wr']:>6.1f}% {s['pnl']:>8.1f} {s['pf']:>6.3f} {s['avg_per_day']:>7.2f} {s['trades_per_day']:>6.2f} {s['pos_months']:>7} {s['max_dd']:>7.1f}")

    # ── 2. Performance per regime ─────────────────────────────────────────────
    print("\n" + "="*65)
    print("FASE 2: Performance per strategia × regime")
    print("="*65)

    regime_strategy_stats = defaultdict(lambda: defaultdict(list))
    for name, res in strategy_results.items():
        for t in res['trades']:
            # detect regime per quel trade — usa il regime del giorno se disponibile
            # (approssimazione: leggi ADX e DIP/DIM dal candle index)
            regime_strategy_stats[name][t.get('regime','N/A')].append(t['pnl'])

    # Trova best strategy per regime basandosi su PF
    print(f"\n{'Regime':<22} {'Best Strategy':<20} {'WR%':>6} {'PF':>6} {'N':>5}")
    print("-"*60)
    regime_best = {}
    for regime in ['TREND_UP','TREND_DOWN','WEAK_TREND_UP','WEAK_TREND_DOWN','RANGE','VOLATILE_RANGE']:
        candidates = REGIME_STRATEGY_CANDIDATES.get(regime,[])
        best_name = None; best_pf = 0; best_wr = 0; best_n = 0
        for name in candidates:
            t_list = strategy_results.get(name,{}).get('trades',[])
            if not t_list: continue
            wins = [t for t in t_list if t['outcome']=='win']
            losses = [t for t in t_list if t['outcome']=='loss']
            gw = sum(t['pnl'] for t in wins) if wins else 0
            gl = abs(sum(t['pnl'] for t in losses)) if losses else 0.001
            pf = gw/gl
            wr = len(wins)/len(t_list)*100 if t_list else 0
            if pf > best_pf:
                best_pf=pf; best_name=name; best_wr=wr; best_n=len(t_list)
        regime_best[regime] = best_name or candidates[0] if candidates else 'EMA_TREND'
        print(f"{regime:<22} {(best_name or '—'):<20} {best_wr:>6.1f}% {best_pf:>6.3f} {best_n:>5}")

    # ── 3. Regime-adaptive backtest ───────────────────────────────────────────
    print("\n" + "="*65)
    print("FASE 3: Sistema ADATTIVO (regime detection + selezione dinamica)")
    print("="*65)
    regime_trades = run_regime_backtest(candles, inds)
    rs = stats(regime_trades)

    print(f"\n  Trade totali:    {rs['n']}")
    print(f"  Win Rate:        {rs['wr']}%")
    print(f"  P&L totale:      ${rs['pnl']}")
    print(f"  Profit Factor:   {rs['pf']}")
    print(f"  Media $/giorno:  ${rs['avg_per_day']}")
    print(f"  Trade/giorno:    {rs['trades_per_day']}")
    print(f"  Mesi positivi:   {rs['pos_months']}")
    print(f"  Max Drawdown:    ${rs['max_dd']}")

    # Breakdown per strategia usata nel sistema adattivo
    adap_by_strat = defaultdict(list)
    for t in regime_trades: adap_by_strat[t['strategy']].append(t)
    print(f"\n  Utilizzo strategie nel sistema adattivo:")
    print(f"  {'Strategia':<20} {'N':>5} {'WR%':>6} {'P&L':>8}")
    for name, tl in sorted(adap_by_strat.items(), key=lambda x:-len(x[1])):
        s2 = stats(tl)
        print(f"  {name:<20} {s2['n']:>5} {s2['wr']:>6.1f}% {s2['pnl']:>8.1f}")

    # Trade per giorno (quanti giorni hanno segnali)
    active_days = set(t['date'] for t in regime_trades)
    print(f"\n  Giorni con almeno 1 trade: {len(active_days)} / ~{RANGE_DAYS} (730gg)")

    # ── 4. Giorni estremi saltati ─────────────────────────────────────────────
    extreme_days = 0
    for i in range(210, len(candles)):
        av = inds['atr'][i]; aa = inds['atr_avg30'][i]
        if av and aa and av > EXTREME_DAY_MULT*aa:
            extreme_days += 1
    print(f"  Ore candele saltate (giorno estremo): {extreme_days} (~{extreme_days//10} giorni)")

    # ── 5. Output JSON ────────────────────────────────────────────────────────
    output = {
        'generated_at': datetime.datetime.utcnow().isoformat(),
        'config': {
            'symbol': SYMBOL, 'interval': INTERVAL,
            'tp_usd': TP_USD, 'sl_usd': SL_USD,
            'max_trades_day': MAX_TRADES_DAY, 'cooldown_h': COOLDOWN_H,
            'extreme_day_mult': EXTREME_DAY_MULT,
            'session_utc': [SESSION_START, SESSION_END]
        },
        'strategies': {
            name: {
                'stats': res['stats'],
                'signal_count': len(res['trades'])
            }
            for name, res in strategy_results.items()
        },
        'regime_best_strategy': regime_best,
        'regime_candidates': REGIME_STRATEGY_CANDIDATES,
        'adaptive_system': {
            'stats': rs,
            'by_strategy': {
                name: stats(tl) for name, tl in adap_by_strat.items()
            }
        },
        'last_100_trades': regime_trades[-100:]
    }

    with open('strategy_engine_results.json','w') as f:
        json.dump(output, f, indent=2, default=str)

    print("\n" + "="*65)
    print("CONFIGURAZIONE FINALE SALVATA: strategy_engine_results.json")
    print("="*65)
    print(f"\n  Sistema adattivo: {rs['wr']}% WR · ${rs['avg_per_day']}/gg · {rs['trades_per_day']:.1f} trade/gg")

if __name__=='__main__':
    main()
