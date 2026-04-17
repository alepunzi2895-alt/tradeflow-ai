"""
TradeFlow AI — MT5 Automated Trading Bot
Collega MetaTrader 5 al motore di strategia H1 su XAUUSD.

PREREQUISITI:
  1. MetaTrader 5 installato e aperto (demo o reale)
  2. pip install MetaTrader5
  3. Configura LOGIN, PASSWORD, SERVER qui sotto

USO:
  python scripts/mt5-bot.py
  python scripts/mt5-bot.py --dry-run   (simula senza inviare ordini)
"""
import sys, io, time, json, math, datetime, argparse, os, logging, urllib.request, urllib.error, ssl
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()
    _SSL_CTX.check_hostname = False
    _SSL_CTX.verify_mode = ssl.CERT_NONE
from dotenv import load_dotenv
load_dotenv() # Carica .env dal root se presente

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ── SIGNAL FUNCTIONS (single source of truth) ────────────────────────────────
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(__file__))
from signals import (
    signal_mfkk_score, signal_mfkk_intraday, signal_golden_squeeze,
    signal_mfkk_scalping, signal_ob_fvg_scalp, signal_convergence_scalp,
)

# ── RISK MANAGER ─────────────────────────────────────────────────────────────
try:
    from risk_manager import get_risk_manager, RiskManager
except ImportError:
    get_risk_manager = None
    log_placeholder = logging.getLogger('tf-bot')
    log_placeholder.warning("risk_manager.py non trovato — uso lot size fisso")

# ── CONFIGURAZIONE (Legacy fallback, ora legge da .env) ───────────────
MT5_LOGIN    = int(os.getenv("MT5_LOGIN", 1301224666))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "Alessandro95!")
MT5_SERVER   = os.getenv("MT5_SERVER", "XMGlobal-MT5 6")

SYMBOL       = os.getenv("SYMBOL", "GOLD")

LOT_SIZE     = 0.05          # lot size base (0.05 = config A ottimizzata, ~€1000+ capital)
MAGIC        = 20250413      # ID univoco per gli ordini di questo bot
MAX_TRADES   = 0             # 0 = nessun limite giornaliero
COOLDOWN_H   = 1             # ore di cooldown tra trade
EXTREME_MULT = 3.0           # ATR > 3x avg = giorno estremo, skip
SESSION_UTC  = (7, 17)       # finestra operativa London+NY (UTC)
CHECK_SEC    = 10            # polling ogni 10 secondi

# Se sei su VPS Standalone, usa http://localhost:3000
VERCEL_URL   = os.getenv("VERCEL_URL", "https://tradeflow-ai-delta.vercel.app") 
MT5_SECRET   = os.getenv("MT5_BOT_SECRET", "tradeflow-mt5-secret") 

SYNC_ENABLED = True          # False per disabilitare il sync cloud

current_ai_score = 50.0      # Global per rilassamento filtri


LOG_FILE     = "mt5-bot.log"

# ── TP/SL per strategia ───────────────────────────────────────────────────────
# GOLD su XM: 1 punto = $0.01 (digits=2). TP=$20 → 2000 punti.
STRATEGY_PARAMS = {
    'S05_MFKK_INTRADAY':   {'tp_usd': 'ATR', 'sl_usd': 'ATR', 'label': 'MFKK Intraday V3', 'tp_mult': 2.0, 'sl_mult': 1.0},
    'S09_MFKK_SCALPING':   {'tp_usd': 'ATR', 'sl_usd': 'ATR', 'label': 'MFKK Scalping V2', 'tp_mult': 3.0, 'sl_mult': 1.0},
    'S10_OB_FVG_SCALP':    {'tp_usd': 'ATR', 'sl_usd': 'ATR', 'label': 'OB+FVG Scalp V2', 'tp_mult': 2.5, 'sl_mult': 1.2},
    'S16_GOLDEN_SQUEEZE':  {'tp_usd': 'ATR', 'sl_usd': 'ATR', 'label': 'Golden Squeeze V2', 'tp_mult': 3.0, 'sl_mult': 1.2, 'be_mult': 1.1},
    'S17_CONVERGENCE_SCALP': {'tp_usd': 'ATR', 'sl_usd': 'ATR', 'label': 'Convergence Scalp V2', 'tp_mult': 2.5, 'sl_mult': 0.8},
}

# Playbook caricato da regime_playbook.json al boot; fallback hardcoded
PLAYBOOK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'regime_playbook.json')
FALLBACK_PLAYBOOK = {
    'TREND_UP':   {'strategy': 'S16_GOLDEN_SQUEEZE',   'tf': 'M30'},
    'TREND_DOWN': {'strategy': 'S16_GOLDEN_SQUEEZE',   'tf': 'M30'},
    'WEAK_UP':    {'strategy': 'S16_GOLDEN_SQUEEZE',   'tf': 'M30'},
    'WEAK_DOWN':  {'strategy': 'S16_GOLDEN_SQUEEZE',   'tf': 'M30'},
    'VOLATILE':   {'strategy': 'S09_MFKK_SCALPING',    'tf': 'M5'},
    'RANGE':      {'strategy': 'S10_OB_FVG_SCALP',     'tf': 'M30'},
    'UNKNOWN':    {'strategy': 'S16_GOLDEN_SQUEEZE',   'tf': 'M30'},
}
PLAYBOOK = FALLBACK_PLAYBOOK  # verrà sovrascritta da load_playbook()

# ── LOGGING ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger('tf-bot')

# ── ARGPARSE ──────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description='TradeFlow AI MT5 Bot')
parser.add_argument('--dry-run', action='store_true', help='Simula senza inviare ordini reali')
args = parser.parse_args()
DRY_RUN = args.dry_run

if DRY_RUN:
    log.info("*** DRY-RUN MODE — nessun ordine reale verrà inviato ***")

# ── IMPORT MT5 ────────────────────────────────────────────────────────────────
try:
    import MetaTrader5 as mt5
except ImportError:
    log.error("MetaTrader5 non installato. Esegui: pip install MetaTrader5")
    sys.exit(1)

# ── MATH HELPERS (identici a strategy-engine-v2.py) ──────────────────────────
def ema(src, p):
    k=2/(p+1); v=src[0]; o=[v]
    for i in range(1,len(src)): v=src[i]*k+v*(1-k); o.append(v)
    return o

def sma(src, p):
    o=[None]*(p-1)
    for i in range(p-1,len(src)):
        o.append(sum(src[i-p+1:i+1])/p)
    return o

def rsi(src, p=14):
    n=len(src); out=[None]*n
    g=[max(0,src[i]-src[i-1]) for i in range(1,n)]
    l=[max(0,src[i-1]-src[i]) for i in range(1,n)]
    if len(g)<p: return out
    ag=sum(g[:p])/p; al=sum(l[:p])/p
    out[p]=100-100/(1+(ag/al if al>0 else 100))
    for i in range(p,len(g)):
        ag=(ag*(p-1)+g[i])/p; al=(al*(p-1)+l[i])/p
        out[i+1]=100-100/(1+(ag/al if al>0 else 100))
    return out

def atr(H,L,C,p=14):
    tr=[0]
    for i in range(1,len(C)):
        tr.append(max(H[i]-L[i],abs(H[i]-C[i-1]),abs(L[i]-C[i-1])))
    return sma(tr,p)

def macd(src, fast=12, slow=26, sig=9):
    ef=ema(src,fast); es=ema(src,slow)
    line=[ef[i]-es[i] for i in range(len(src))]
    signal=ema(line,sig)
    hist=[line[i]-signal[i] for i in range(len(src))]
    return line, signal, hist

def adx_calc(H,L,C,p=14):
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

def bb(src,p=20,mult=2.0):
    mid=sma(src,p)
    up=[None]*len(src); dn=[None]*len(src)
    for i in range(p-1,len(src)):
        sd=math.sqrt(sum((src[i-j]-mid[i])**2 for j in range(p))/p)
        up[i]=mid[i]+mult*sd; dn[i]=mid[i]-mult*sd
    return mid, up, dn

def wpr(H,L,C,p=14):
    out=[None]*len(C)
    for i in range(p-1,len(C)):
        hh=max(H[i-p+1:i+1]); ll=min(L[i-p+1:i+1])
        out[i]=-100*(hh-C[i])/(hh-ll) if hh!=ll else -50
    return out

def keltner(H,L,C,p=20,mult=2.0):
    mid=ema(C,p); a=atr(H,L,C,p)
    up=[mid[i]+mult*a[i] if a[i] else None for i in range(len(C))]
    dn=[mid[i]-mult*a[i] if a[i] else None for i in range(len(C))]
    return mid,up,dn

def vwap_intraday(candles):
    out=[None]*len(candles)
    cum_pv=0; cum_v=0; cur_date=None
    for i,c in enumerate(candles):
        dt=datetime.datetime.fromtimestamp(c['t'],tz=datetime.timezone.utc).date()
        if dt!=cur_date: cum_pv=0; cum_v=0; cur_date=dt
        tp=(c['h']+c['l']+c['c'])/3
        cum_pv+=tp*c['v']; cum_v+=c['v']
        out[i]=cum_pv/cum_v if cum_v>0 else c['c']
    return out

def obv(C,V):
    out=[0.0]
    for i in range(1,len(C)):
        out.append(out[-1]+(V[i] if C[i]>C[i-1] else -V[i] if C[i]<C[i-1] else 0))
    return out

# ── MATH HELPERS AGGIUNTIVI ──────────────────────────────────────────────────
def cci(H, L, C, p=50):
    tp = [(H[i]+L[i]+C[i])/3 for i in range(len(C))]
    out = [None]*(p-1)
    for i in range(p-1, len(tp)):
        sl = tp[i-p+1:i+1]; mn = sum(sl)/p
        md = sum(abs(x-mn) for x in sl)/p
        out.append((tp[i]-mn)/(0.015*md) if md > 0 else 0)
    return out

def mom(src, p=10):
    out = [None]*p
    for i in range(p, len(src)):
        out.append(src[i]-src[i-p])
    return out

def dema(src, p):
    m1 = ema(src, p); m2 = ema(m1, p)
    return [2*m1[i]-m2[i] for i in range(len(src))]

def stdev_arr(src, p):
    out = [None]*(p-1)
    for i in range(p-1, len(src)):
        sl = src[i-p+1:i+1]; mn = sum(sl)/p
        out.append(math.sqrt(sum((x-mn)**2 for x in sl)/p))
    return out

def calc_fvg(O, H, L, C, std_len=100, df=2):
    """Fair Value Gap — rileva zone FVG bullish/bearish per S09_MFKK_SCALPING."""
    n = len(C)
    body = [abs(O[i]-C[i]) for i in range(n)]
    bs = stdev_arr(body, std_len)
    fb = [False]*n; fs = [False]*n
    ab = []; as_ = []
    for i in range(2, n):
        disp = bs[i-1] is not None and bs[i-1] > 0 and body[i-1] > bs[i-1]*df
        if L[i] > H[i-2]: ab.append({'lo': H[i-2], 'hi': L[i], 'bar': i, 'd': disp})
        if H[i] < L[i-2]: as_.append({'lo': H[i], 'hi': L[i-2], 'bar': i, 'd': disp})
        sb = []
        for fvg in ab:
            if fvg['bar'] == i: sb.append(fvg); continue
            if L[i] < fvg['lo']: continue
            if C[i] <= fvg['hi'] and C[i] >= fvg['lo']: fb[i] = True
            sb.append(fvg)
        ab = sb[-20:]
        sb2 = []
        for fvg in as_:
            if fvg['bar'] == i: sb2.append(fvg); continue
            if H[i] > fvg['hi']: continue
            if C[i] >= fvg['lo'] and C[i] <= fvg['hi']: fs[i] = True
            sb2.append(fvg)
        as_ = sb2[-20:]
    return fb, fs

def calc_order_blocks(O, H, L, C, lookback=30):
    """
    Order Block detection per S10_OB_FVG_SCALP.
    Relaxed version: lookback 30, lower mitigation requirement, higher tolerance.
    """
    n = len(C)
    ob_bull = [False]*n
    ob_bear = [False]*n
    for i in range(lookback + 4, n):
        c_now = C[i]
        # ── Bullish OB ───────────────────────────────────────────────────────
        for j in range(i - 2, max(i - lookback - 1, 2), -1):
            if C[j] >= O[j]: continue
            ob_lo = min(O[j], C[j]); ob_hi = max(O[j], C[j])
            if not (j+1 < n and C[j+1] > O[j+1]): continue # almeno 1 candela bull
            if any(L[k] < ob_lo * 0.998 for k in range(j+1, i)): continue
            if ob_lo * 0.998 <= c_now <= ob_hi * 1.003:
                ob_bull[i] = True; break
        # ── Bearish OB ───────────────────────────────────────────────────────
        for j in range(i - 2, max(i - lookback - 1, 2), -1):
            if C[j] <= O[j]: continue
            ob_lo = min(O[j], C[j]); ob_hi = max(O[j], C[j])
            if not (j+1 < n and C[j+1] < O[j+1]): continue
            if any(H[k] > ob_hi * 1.002 for k in range(j+1, i)): continue
            if ob_lo * 0.997 <= c_now <= ob_hi * 1.002:
                ob_bear[i] = True; break
    return ob_bull, ob_bear

def obv_macd_tchannel(H, L, C, V, wl=28, vl=14, ml=9, sl=26):
    """OBV MACD T-Channel — identico al Pine Script originale"""
    n = len(C)
    obv_v = [0.0]
    for i in range(1, n):
        s = 1 if C[i] > C[i-1] else (-1 if C[i] < C[i-1] else 0)
        obv_v.append(obv_v[-1] + s*(V[i] or 0))
    hl = [H[i]-L[i] for i in range(n)]
    ps = stdev_arr(hl, wl)
    sm = sma(obv_v, vl)
    vd = [obv_v[i]-(sm[i] or 0) for i in range(n)]
    vs = stdev_arr(vd, wl)
    out = []
    for i in range(n):
        if sm[i] is None or not vs[i] or not ps[i]: out.append(C[i]); continue
        sh = (obv_v[i]-sm[i])/vs[i]*ps[i]
        out.append(H[i]+sh if sh > 0 else L[i]+sh)
    dm = dema(out, ml); slw = ema(C, sl)
    ml_ = [dm[i]-slw[i] for i in range(n)]
    b5 = [ml_[0]]; oc = [0]; cd = 0.0
    for i in range(1, n):
        cd += abs(ml_[i]-b5[-1]); a = cd/i
        if   ml_[i] > b5[-1]+a: b5.append(ml_[i])
        elif ml_[i] < b5[-1]-a: b5.append(ml_[i])
        else: b5.append(b5[-1])
        if   b5[-1] > b5[-2]: oc.append(1)
        elif b5[-1] < b5[-2]: oc.append(-1)
        else: oc.append(oc[-1])
    return ml_, b5, oc

def supertrend(H, L, C, p=10, m=3.0):
    atr_v = atr(H, L, C, p)
    n = len(C); dir_ = [1]*n; st = [0.0]*n
    ub = [(H[i]+L[i])/2+m*(atr_v[i] or 0) for i in range(n)]
    lb = [(H[i]+L[i])/2-m*(atr_v[i] or 0) for i in range(n)]
    f_ub = [0.0]*n; f_lb = [0.0]*n
    for i in range(1, n):
        f_ub[i] = ub[i] if ub[i]<f_ub[i-1] or C[i-1]>f_ub[i-1] else f_ub[i-1]
        f_lb[i] = lb[i] if lb[i]>f_lb[i-1] or C[i-1]<f_lb[i-1] else f_lb[i-1]
        if st[i-1]==f_ub[i-1] and C[i]<=f_ub[i]: st[i]=f_ub[i]; dir_[i]=1
        elif st[i-1]==f_ub[i-1] and C[i]>f_ub[i]: st[i]=f_lb[i]; dir_[i]=-1
        elif st[i-1]==f_lb[i-1] and C[i]>=f_lb[i]: st[i]=f_lb[i]; dir_[i]=-1
        elif st[i-1]==f_lb[i-1] and C[i]<f_lb[i]: st[i]=f_ub[i]; dir_[i]=1
        else: st[i]=f_ub[i]; dir_[i]=1
    return dir_  # 1=bearish, -1=bullish

def alligator(H, L, p1=13, p2=8, p3=5):
    med = [(H[i]+L[i])/2 for i in range(len(H))]
    jaw = ema(med, p1)
    teeth = ema(med, p2)
    lips = ema(med, p3)
    return jaw, teeth, lips

def stoch_rsi(src, rsi_p=14, stoch_p=14, k_p=3, d_p=3):
    r = rsi(src, rsi_p)
    n = len(r); stoch = [None]*n
    for i in range(rsi_p, n):
        sl = [x for x in r[i-rsi_p+1:i+1] if x is not None]
        if len(sl) < rsi_p or r[i] is None: continue
        lo = min(sl); hi = max(sl)
        stoch[i] = (r[i]-lo)/(hi-lo)*100 if hi>lo else 50
    sk = sma([x if x is not None else 50 for x in stoch], k_p)
    sd = sma([x if x is not None else 50 for x in sk], d_p)
    return sk, sd

def bb(src, p=20, m=2.0):
    mid=sma(src,p); up=[]; dn=[]
    for i,v in enumerate(mid):
        if v is None: up.append(None);dn.append(None);continue
        sl=src[i-p+1:i+1]
        mn=sum(sl)/p; std=math.sqrt(sum((x-mn)**2 for x in sl)/p)
        up.append(v+m*std); dn.append(v-m*std)
    return mid, up, dn

# ── COMPUTE INDICATORS ────────────────────────────────────────────────────────
def compute_indicators(candles):
    O=[c['o'] for c in candles]
    H=[c['h'] for c in candles]
    L=[c['l'] for c in candles]
    C=[c['c'] for c in candles]
    V=[c['v'] for c in candles]
    n=len(C)
    I={}
    I['O']=O; I['C']=C; I['H']=H; I['L']=L; I['V']=V
    I['e13']=ema(C,13); I['e34']=ema(C,34)
    I['e89']=ema(C,89); I['e233']=ema(C,233)
    I['e20']=ema(C,20); I['e50']=ema(C,50)
    I['e100']=ema(C,100); I['e200']=ema(C,200)
    I['rsi']=rsi(C,14)
    I['atr']=atr(H,L,C,14)
    I['adx'],I['dip'],I['dim']=adx_calc(H,L,C,14)
    I['ml'],I['ms'],I['mh']=macd(C,12,26,9)
    I['macd_sig']=I['ms']   # alias usato da s_exhaustion
    I['cci']=cci(H,L,C,50)
    I['mom']=mom(C,10)
    I['bb_mid'],I['bb_up'],I['bb_dn']=bb(C,20,2.0)
    I['wpr']=wpr(H,L,C,14)
    I['km'],I['ku'],I['kl']=keltner(H,L,C,20,2.0)
    I['vwap']=vwap_intraday(candles)
    I['obv']=obv(C,V)
    I['obv_ema']=ema(I['obv'],20)
    I['srsi_k'],I['srsi_d']=stoch_rsi(C,14,3,3)
    I['jaw'], I['teeth'], I['lips'] = alligator(H, L)
    I['st'] = supertrend(H, L, C, 10, 3.0)
    # OBV MACD T-Channel per S05_MFKK_INTRADAY / S05_V3_Sell_Exhaust
    try:
        _, _, I['obv_oc'] = obv_macd_tchannel(H,L,C,V)
    except Exception:
        I['obv_oc'] = [0]*n
    # FVG per S09_MFKK_SCALPING e S10_OB_FVG_SCALP
    try:
        I['fvg_bull'], I['fvg_bear'] = calc_fvg(O,H,L,C)
    except Exception:
        I['fvg_bull'] = [False]*n; I['fvg_bear'] = [False]*n
    # Order Blocks per S10_OB_FVG_SCALP
    try:
        I['ob_bull'], I['ob_bear'] = calc_order_blocks(O,H,L,C)
    except Exception:
        I['ob_bull'] = [False]*n; I['ob_bear'] = [False]*n
    # ATR rolling avg 30 bar
    I['atr_avg']=[None]*n
    for i in range(30,n):
        vals=[I['atr'][j] for j in range(i-30,i) if I['atr'][j] is not None]
        I['atr_avg'][i]=sum(vals)/len(vals) if vals else None

    return I

# ── REGIME DETECTION ─────────────────────────────────────────────────────────
def detect_regime(I, i):
    adx_v = I['adx'][i]; dip_v = I['dip'][i]; dim_v = I['dim'][i]
    atr_v = I['atr'][i]; atr_avg = I['atr_avg'][i]
    if adx_v is None: return 'UNKNOWN'
    if atr_v and atr_avg and atr_v > EXTREME_MULT * atr_avg:
        return 'EXTREME'
    if adx_v >= 30:
        return 'TREND_UP' if dip_v > dim_v else 'TREND_DOWN'
    if adx_v >= 22:
        return 'WEAK_UP' if dip_v > dim_v else 'WEAK_DOWN'
    if atr_v and atr_avg and atr_v > 1.4 * atr_avg:
        return 'VOLATILE'
    return 'RANGE'

# ── STRATEGY SIGNALS — imported from scripts/signals.py ─────────────────────
# signal_mfkk_score, signal_mfkk_intraday, signal_golden_squeeze,
# signal_mfkk_scalping, signal_ob_fvg_scalp, signal_convergence_scalp

SIGNAL_FNS = {
    'S00_MFKK':             signal_mfkk_score,
    'S05_MFKK_INTRADAY':    signal_mfkk_intraday,
    'S09_MFKK_SCALPING':    signal_mfkk_scalping,
    'S10_OB_FVG_SCALP':     signal_ob_fvg_scalp,
    'S16_GOLDEN_SQUEEZE':   signal_golden_squeeze,
    'S17_CONVERGENCE_SCALP': signal_convergence_scalp,
}

# Asian session (00:00–07:59 UTC): low XAU/USD liquidity, high spreads — skip S16
SESSION_FILTER = {
    'S16_GOLDEN_SQUEEZE': {'block_hours': range(0, 8)},
}

# Multi-strategy map: (strategy_id, tf, direction_filter) per regime
# Identico a backtest_combined.py — S00_MFKK su tutti i regimi (BUY>=80/SELL>=65)
REGIME_MULTI_STRATEGIES = {
    'TREND_UP':   [('S16_GOLDEN_SQUEEZE','M30',None), ('S05_MFKK_INTRADAY','H1',None), ('S17_CONVERGENCE_SCALP','M15',None)],
    'TREND_DOWN': [('S16_GOLDEN_SQUEEZE','M30',None), ('S05_MFKK_INTRADAY','H1',None), ('S17_CONVERGENCE_SCALP','M15',None)],
    'WEAK_UP':    [('S16_GOLDEN_SQUEEZE','M30',None), ('S10_OB_FVG_SCALP','M30',None), ('S09_MFKK_SCALPING','M5',None), ('S17_CONVERGENCE_SCALP','M15',None)],
    'WEAK_DOWN':  [('S16_GOLDEN_SQUEEZE','M30',None), ('S10_OB_FVG_SCALP','M30',None), ('S09_MFKK_SCALPING','M5',None), ('S17_CONVERGENCE_SCALP','M15',None)],
    'VOLATILE':   [('S09_MFKK_SCALPING','M5',None), ('S10_OB_FVG_SCALP','M30',None), ('S17_CONVERGENCE_SCALP','M15',None)],
    'RANGE':      [('S10_OB_FVG_SCALP','M30',None), ('S09_MFKK_SCALPING','M5',None), ('S17_CONVERGENCE_SCALP','M5',None)],
    'UNKNOWN':    [('S16_GOLDEN_SQUEEZE','M30',None), ('S17_CONVERGENCE_SCALP','M15',None)],
}

def get_signal(I, i, hour, regime):
    """Restituisce (strategia, direzione) per strategie H1.
    Le strategie M15/M30 sono gestite direttamente nel loop principale.
    """
    entry = PLAYBOOK.get(regime) or PLAYBOOK.get('UNKNOWN', {'strategy': 'S00_MFKK', 'tf': 'H1'})
    if entry.get('tf', 'H1') != 'H1':
        return None, None   # gestito dal blocco M15/M30 nel loop
    sname = entry['strategy']
    fn = SIGNAL_FNS.get(sname)
    if fn is None:
        return None, None
    if sname == 'S05_MFKK_INTRADAY':
        direction = fn(I, i, ai_score=current_ai_score)
    else:
        direction = fn(I, i)
    return (sname, direction) if direction else (None, None)

# ── STATO GIORNALIERO ─────────────────────────────────────────────────────────
class DailyState:
    def __init__(self):
        self.date = None
        self.trades_today = 0
        self.last_trade_time = None
        self.pnl_today = 0.0

    def reset_if_new_day(self):
        today = datetime.date.today()
        if self.date != today:
            self.date = today
            self.trades_today = 0
            self.last_trade_time = None
            self.pnl_today = 0.0
            log.info(f"=== Nuovo giorno: {today} — stato reset ===")

    def can_trade(self, now_utc):
        self.reset_if_new_day()
        if MAX_TRADES > 0 and self.trades_today >= MAX_TRADES:
            return False, f"Raggiunto max trade/giorno ({MAX_TRADES})"
        hour_utc = now_utc.hour
        if hour_utc < SESSION_UTC[0] or hour_utc >= SESSION_UTC[1]:
            return False, f"Fuori sessione ({hour_utc}h UTC)"
        if self.last_trade_time:
            elapsed_h = (now_utc - self.last_trade_time).total_seconds() / 3600
            if elapsed_h < COOLDOWN_H:
                remaining = round((COOLDOWN_H - elapsed_h)*60)
                return False, f"Cooldown attivo ({remaining} min rimanenti)"
        return True, "OK"

    def record_trade(self, pnl, now_utc):
        self.trades_today += 1
        self.last_trade_time = now_utc
        self.pnl_today += pnl

state = DailyState()

# ── MT5 HELPERS ───────────────────────────────────────────────────────────────
def mt5_connect():
    if not mt5.initialize():
        log.error(f"MT5 initialize() fallito: {mt5.last_error()}")
        return False
    if MT5_LOGIN and MT5_PASSWORD and MT5_SERVER:
        ok = mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER)
        if not ok:
            log.error(f"MT5 login fallito: {mt5.last_error()}")
            return False
        log.info(f"MT5 connesso — conto #{MT5_LOGIN}")
    else:
        info = mt5.account_info()
        if info is None:
            log.error("MT5 non loggato e credenziali non configurate.")
            return False
        log.info(f"MT5 connesso — conto #{info.login} ({info.name}) @ {info.server}")
    return True

_TF_MT5_MAP = None  # popolato lazy dopo mt5.initialize()

def _tf_enum(tf):
    return {
        'M5':  mt5.TIMEFRAME_M5,
        'M15': mt5.TIMEFRAME_M15,
        'M30': mt5.TIMEFRAME_M30,
        'H1':  mt5.TIMEFRAME_H1,
        'H4':  mt5.TIMEFRAME_H4,
        'D1':  mt5.TIMEFRAME_D1,
    }.get(tf, mt5.TIMEFRAME_H1)

def _rates_to_list(rates):
    candles = []
    for r in rates:
        candles.append({
            't': int(r['time']),
            'o': float(r['open']),
            'h': float(r['high']),
            'l': float(r['low']),
            'c': float(r['close']),
            'v': float(r['tick_volume']),
        })
    return candles

def get_candles(n=300):
    """Recupera le ultime N candele H1 da MT5"""
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, n)
    if rates is None or len(rates) == 0:
        return None
    return _rates_to_list(rates)

def get_candles_tf(tf, n=450):
    """Recupera le ultime N candele per qualsiasi timeframe (M5/M15/M30/H1/H4/D1)."""
    rates = mt5.copy_rates_from_pos(SYMBOL, _tf_enum(tf), 0, n)
    if rates is None or len(rates) == 0:
        log.warning(f"get_candles_tf({tf}): nessun dato — {mt5.last_error()}")
        return None
    return _rates_to_list(rates)

def load_playbook():
    """Carica regime_playbook.json; aggiorna PLAYBOOK globale."""
    global PLAYBOOK
    try:
        with open(PLAYBOOK_FILE, encoding='utf-8') as f:
            data = json.load(f)
        pb_raw = data.get('playbook', {})
        pb = {}
        for regime, info in pb_raw.items():
            pb[regime] = {'strategy': info['strategy'], 'tf': info.get('tf', 'H1')}
        pb.setdefault('UNKNOWN', {'strategy': 'S00_MFKK', 'tf': 'H1'})
        PLAYBOOK = pb
        entries = ', '.join(f"{r}→{v['strategy']}/{v['tf']}" for r, v in pb.items() if r != 'UNKNOWN')
        log.info(f"Playbook caricato ({len(pb)-1} regimi): {entries}")
    except Exception as e:
        log.warning(f"Playbook non caricato ({e}) — uso fallback hardcoded")

def get_account_info():
    info = mt5.account_info()
    if info is None: return None
    return {
        'balance': info.balance,
        'equity': info.equity,
        'margin_free': info.margin_free,
        'currency': info.currency,
    }

def count_open_positions():
    pos = mt5.positions_get(symbol=SYMBOL)
    if pos is None: return 0
    return len([p for p in pos if p.magic == MAGIC])

def has_position_in_direction(direction):
    """True se esiste già una posizione aperta nella direzione specificata."""
    for p in mt5.positions_get(symbol=SYMBOL) or []:
        if p.magic != MAGIC: continue
        if direction == 'buy'  and p.type == mt5.ORDER_TYPE_BUY:  return True
        if direction == 'sell' and p.type == mt5.ORDER_TYPE_SELL: return True
    return False

def place_order(direction, tp_usd, sl_usd, strategy_name, lot_size=None):
    """Invia un ordine market su MT5 con lot size adattivo da RiskManager"""
    tick = mt5.symbol_info_tick(SYMBOL)
    sym_info = mt5.symbol_info(SYMBOL)
    if tick is None or sym_info is None:
        log.error("Impossibile ottenere tick/info simbolo")
        return None

    digits = sym_info.digits
    lot = lot_size if lot_size else LOT_SIZE

    # Risolvi ATR-based TP/SL (se 'ATR' stringa, usa valore calcolato)
    if not isinstance(tp_usd, (int, float)) or tp_usd <= 0:
        tp_usd = 20.0
    if not isinstance(sl_usd, (int, float)) or sl_usd <= 0:
        sl_usd = 12.0

    if direction == 'buy':
        order_type = mt5.ORDER_TYPE_BUY
        price = tick.ask
        tp_price = round(price + tp_usd, digits)
        sl_price = round(price - sl_usd, digits)
    else:
        order_type = mt5.ORDER_TYPE_SELL
        price = tick.bid
        tp_price = round(price - tp_usd, digits)
        sl_price = round(price + sl_usd, digits)

    request = {
        "action":    mt5.TRADE_ACTION_DEAL,
        "symbol":    SYMBOL,
        "volume":    lot,
        "type":      order_type,
        "price":     price,
        "sl":        sl_price,
        "tp":        tp_price,
        "deviation": 20,
        "magic":     MAGIC,
        "comment":   f"TF-AI {strategy_name}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    if DRY_RUN:
        log.info(f"[DRY-RUN] Ordine simulato: {direction.upper()} {lot} {SYMBOL} "
                 f"@ {price:.2f}  TP={tp_price:.2f}  SL={sl_price:.2f}  [{strategy_name}]")
        return {'retcode': 10009, 'simulated': True}

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log.error(f"Ordine fallito: retcode={result.retcode} — {result.comment}")
        return None
    log.info(f"✓ Ordine eseguito: #{result.order} {direction.upper()} {lot} {SYMBOL} "
             f"@ {price:.2f}  TP={tp_price:.2f}  SL={sl_price:.2f}  [{strategy_name}]")
    return result

def log_trade_to_json(direction, strategy, price, tp, sl, result):
    """Appende il trade a mt5-trades.json"""
    entry = {
        'time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'direction': direction,
        'strategy': strategy,
        'price': price,
        'tp': tp,
        'sl': sl,
        'lot': LOT_SIZE,
        'dry_run': DRY_RUN,
        'result': str(result),
    }
    fname = 'mt5-trades.json'
    trades = []
    if os.path.exists(fname):
        with open(fname, encoding='utf-8') as f:
            try: trades = json.load(f)
            except: trades = []
    trades.append(entry)
    with open(fname, 'w', encoding='utf-8') as f:
        json.dump(trades, f, indent=2, ensure_ascii=False)

# ── VERCEL SYNC ───────────────────────────────────────────────────────────────
def get_open_positions_data():
    """Legge le posizioni aperte da MT5 e le serializza"""
    pos = mt5.positions_get(symbol=SYMBOL)
    if not pos: return []
    result = []
    for p in pos:
        if p.magic != MAGIC: continue
        result.append({
            'ticket':    p.ticket,
            'direction': 'buy' if p.type == 0 else 'sell',
            'lot':       p.volume,
            'entry':     round(p.price_open, 2),
            'current':   round(p.price_current, 2),
            'tp':        round(p.tp, 2),
            'sl':        round(p.sl, 2),
            'profit':    round(p.profit, 2),
            'strategy':  p.comment.replace('TF-AI ', ''),
            'time':      datetime.datetime.fromtimestamp(p.time, tz=datetime.timezone.utc).isoformat(),
        })
    return result

def get_recent_trades_data(n=30):
    """
    Legge gli ultimi N deal chiusi direttamente da MT5 (storico reale).
    Fallback su mt5-trades.json se MT5 non disponibile.
    """
    try:
        utc = datetime.timezone.utc
        from_date = datetime.datetime.now(utc) - datetime.timedelta(days=180)
        to_date   = datetime.datetime.now(utc)
        deals = mt5.history_deals_get(from_date, to_date)
        total = len(deals) if deals is not None else 0
        log.info(f"📋 history_deals raw: {total} deal (180gg)")
        if deals is not None and total > 0:
            # Log ultimi 10 deal per diagnostica
            for d in sorted(deals, key=lambda x: x.time, reverse=True)[:10]:
                dt = datetime.datetime.fromtimestamp(d.time, tz=utc).strftime('%m-%d %H:%M')
                log.info(f"  deal {dt} type={d.type} entry={d.entry} profit={d.profit:.2f} comment={d.comment!r}")
            result = []
            for d in sorted(deals, key=lambda x: x.time, reverse=True):
                if d.type not in (0, 1):
                    continue
                # entry: 0=IN, 1=OUT, 2=INOUT, 3=OUT_BY (hedge)
                if d.entry == 0:
                    continue
                result.append({
                    'ticket':    d.ticket,
                    'time':      datetime.datetime.fromtimestamp(d.time, tz=utc).isoformat(),
                    'direction': 'sell' if d.type == 0 else 'buy',
                    'strategy':  d.comment.replace('TF-AI ', '') if d.comment else 'N/A',
                    'price':     round(d.price, 2),
                    'profit':    round(d.profit, 2),
                    'volume':    d.volume,
                })
                if len(result) >= n: break
            log.info(f"📋 Trade chiusi: {len(result)}")
            if result:
                return result
    except Exception as e:
        log.warning(f"MT5 history_deals errore: {e}")
    # Fallback su file locale
    fname = 'mt5-trades.json'
    if not os.path.exists(fname): return []
    with open(fname, encoding='utf-8') as f:
        try: trades = json.load(f)
        except: return []
    return trades[-n:]

def sync_to_vercel(acc, positions, trades, bot_status):
    """Invia lo stato corrente alla UI su Vercel"""
    if not SYNC_ENABLED or not VERCEL_URL: return
    payload = json.dumps({
        'action': 'mt5_push',
        'secret': MT5_SECRET,
        'account': acc,
        'positions': positions,
        'trades': trades,
        'bot_status': bot_status,
    }).encode('utf-8')
    try:
        req = urllib.request.Request(
            f"{VERCEL_URL}/api/db",
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as r:
            body = r.read().decode('utf-8')
            if r.status == 200:
                log.info(f"✅ Sync Vercel OK — {len(positions)} posizioni, {len(trades)} trade")
            else:
                log.warning(f"⚠️ Sync Vercel HTTP {r.status}: {body[:200]}")
    except Exception as e:
        log.warning(f"❌ Sync Vercel fallito: {e}")

def fetch_pending_command():
    """Controlla se la UI ha inviato un comando manuale da eseguire su MT5"""
    if not SYNC_ENABLED or not VERCEL_URL: return None
    try:
        payload = json.dumps({
            'action': 'mt5_command_get',
            'secret': MT5_SECRET,
        }).encode('utf-8')
        req = urllib.request.Request(
            f"{VERCEL_URL}/api/db",
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=8, context=_SSL_CTX) as r:
            if r.status == 200:
                data = json.loads(r.read().decode('utf-8'))
                if data.get('ok') and data.get('command'):
                    return data['command']
    except Exception as e:
        log.debug(f"fetch_pending_command fallito: {e}")
    return None


# ── LOOP PRINCIPALE ───────────────────────────────────────────────────────────
def run():
    log.info("="*60)
    log.info("TradeFlow AI — MT5 Bot avviato")
    log.info(f"Symbol: {SYMBOL} | Lot: {LOT_SIZE} | Max trade/gg: {'illimitato' if MAX_TRADES==0 else MAX_TRADES}")
    log.info(f"Dry-run: {DRY_RUN}")
    log.info("="*60)

    if not mt5_connect():
        log.error("Connessione MT5 fallita. Assicurati che MT5 sia aperto e configurato.")
        sys.exit(1)

    load_playbook()

    acc = get_account_info()
    if acc:
        log.info(f"Account: {acc['balance']:.2f} {acc['currency']} "
                 f"(equity={acc['equity']:.2f}, free margin={acc['margin_free']:.2f})")

    last_bar_time      = None   # per rilevare nuova candela H1
    last_bar_time_m15  = None   # per rilevare nuova candela M15
    last_bar_time_m30  = None   # per rilevare nuova candela M30
    current_regime     = 'UNKNOWN'
    current_is_extreme = False
    last_sync_time       = -999  # forza sync immediato al primo ciclo
    last_ai_score        = 50.0  # default neutro
    last_score_ts        = 0     # timestamp ultimo fetch score
    last_cmd_ts          = 0     # timestamp ultimo check comandi manuali
    reconnect_attempts   = 0     # contatore per exponential backoff MT5
    last_candle_fetch_ts = 0     # timestamp ultimo fetch candele H1
    cached_candles       = None  # cache candele (aggiornata ogni 60s)
    cached_I_h1          = None  # cache indicatori (ricalcolati solo su nuova barra)

    # Inizializza RiskManager
    rm = get_risk_manager(base_lot=LOT_SIZE, max_lot=LOT_SIZE*5) if get_risk_manager else None
    if rm:
        log.info(f"RiskManager attivo — base_lot={LOT_SIZE} max_lot={LOT_SIZE*5}")
    else:
        log.warning("RiskManager disabilitato — uso lot size fisso")

    while True:
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            now_ts  = time.time()

            # ── Recupera candele H1 (cache 60s — evita fetch MT5 ad ogni tick) ─
            if now_ts - last_candle_fetch_ts >= 60:
                new_c = get_candles(300)
                if new_c and len(new_c) >= 100:
                    cached_candles = new_c
                    last_candle_fetch_ts = now_ts
            if cached_candles is None or len(cached_candles) < 100:
                log.warning("Candele H1 non disponibili, riprovo...")
                time.sleep(30)
                continue
            candles = cached_candles

            # ── Controlla comandi manuali dalla UI (ogni 5s) ──────────────────
            if now_ts - last_cmd_ts >= 5:
                last_cmd_ts = now_ts
                manual_cmd = fetch_pending_command()
                if manual_cmd:
                    direction = manual_cmd.get('direction')
                    strategy  = manual_cmd.get('strategy', 'S00_MFKK')
                    age_s = (datetime.datetime.now(datetime.timezone.utc) - 
                             datetime.datetime.fromisoformat(manual_cmd.get('created_at', '2000-01-01T00:00:00')
                             .replace('Z', '+00:00'))).total_seconds()
                    if age_s > 60:
                        log.warning(f"⚠ Comando manuale scaduto ({age_s:.0f}s fa) — ignorato")
                    elif direction not in ('buy', 'sell'):
                        log.warning(f"⚠ Comando manuale con direzione invalida: {direction} — ignorato")
                    else:
                        params = STRATEGY_PARAMS.get(strategy, STRATEGY_PARAMS['S00_MFKK'])
                        tp_use = params['tp_usd'] if isinstance(params['tp_usd'], (int, float)) else 20.0
                        sl_use = params['sl_usd'] if isinstance(params['sl_usd'], (int, float)) else 12.0
                        log.info(f"🎯 COMANDO MANUALE UI: {direction.upper()} | {strategy} | TP=${tp_use} SL=${sl_use}")
                        result = place_order(direction, tp_use, sl_use, strategy, lot_size=LOT_SIZE)
                        if result:
                            state.record_trade(0, now_utc)
                            acc_data = get_account_info()
                            sync_to_vercel(
                                acc_data, get_open_positions_data(), get_recent_trades_data(200),
                                {'running': True, 'dry_run': DRY_RUN, 'symbol': SYMBOL,
                                 'lot': LOT_SIZE, 'trades_today': state.trades_today,
                                 'pnl_today': state.pnl_today, 'last_signal': f'MANUAL_{strategy}'}
                            )
                            last_sync_time = now_ts

            # ── Sync periodico a Vercel (ogni 20s) ────────────────────────
            now_ts = time.time()
            if now_ts - last_sync_time >= 20:
                # Verifica connessione MT5 — riconnetti con exponential backoff
                if mt5.account_info() is None:
                    reconnect_attempts += 1
                    wait_s = min(5 * (2 ** (reconnect_attempts - 1)), 300)
                    log.warning(f"MT5 connessione persa — tentativo {reconnect_attempts}, attesa {wait_s}s...")
                    try:
                        mt5.shutdown()
                    except Exception:
                        pass
                    time.sleep(wait_s)
                    if not mt5_connect():
                        log.error(f"Riconnessione MT5 fallita (tentativo {reconnect_attempts})")
                        continue
                    log.info(f"MT5 riconnesso correttamente dopo {reconnect_attempts} tentativi.")
                    reconnect_attempts = 0
                else:
                    reconnect_attempts = 0

                acc_data = get_account_info()
                positions_data = get_open_positions_data()
                trades_data = get_recent_trades_data(200)
                today_str = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
                pnl_today_real = round(sum(t['profit'] for t in trades_data if t['time'][:10] == today_str), 2)
                trades_today_real = sum(1 for t in trades_data if t['time'][:10] == today_str)
                bot_status = {
                    'running': True,
                    'dry_run': DRY_RUN,
                    'symbol': SYMBOL,
                    'lot': LOT_SIZE,
                    'trades_today': trades_today_real,
                    'pnl_today': pnl_today_real,
                    'regime': current_regime,
                    'last_bar': datetime.datetime.fromtimestamp(last_bar_time, tz=datetime.timezone.utc).isoformat() if last_bar_time else None,
                }
                sync_to_vercel(acc_data, positions_data, trades_data, bot_status)
                last_sync_time = now_ts

            # ── Fetch AI Score ogni 60s ────────────────────────────────────
            if (now_ts - last_score_ts) >= 60:
                global current_ai_score
                current_ai_score = RiskManager.fetch_ai_score(VERCEL_URL)
                last_ai_score = current_ai_score
                last_score_ts = now_ts
                if rm:
                    log.info(f"🧠 AI Score aggiornato: {last_ai_score:.1f} — tier: {rm.get_tier(last_ai_score)['label']}")
                else:
                    log.info(f"🧠 AI Score aggiornato: {last_ai_score:.1f}")

            # ── Controlla nuova candela H1 ────────────────────────────────────
            latest_bar_time = candles[-2]['t']   # -2 = ultima barra chiusa
            new_h1_bar = (latest_bar_time != last_bar_time)

            # Ricalcola indicatori solo su nuova barra H1 (1×/ora, non ogni 10s)
            if cached_I_h1 is None or new_h1_bar:
                cached_I_h1 = compute_indicators(candles)
            I_h1 = cached_I_h1
            i_h1 = len(candles) - 2

            if rm:
                atr_now = I_h1['atr'][i_h1] if I_h1['atr'][i_h1] else 10.0
                rm.manage_positions(mt5, SYMBOL, MAGIC, atr_now)

            if new_h1_bar:
                last_bar_time = latest_bar_time
                bar_dt = datetime.datetime.fromtimestamp(latest_bar_time, tz=datetime.timezone.utc)
                log.info(f"─── Nuova barra H1 chiusa: {bar_dt.strftime('%Y-%m-%d %H:%M')} UTC ───")

                # ── Aggiorna Regime ───────────────────────────────────────────
                current_regime = detect_regime(I_h1, i_h1)

                # ── Controllo giorno estremo ──────────────────────────────────
                atr_v   = I_h1['atr'][i_h1]
                atr_avg = I_h1['atr_avg'][i_h1]
                current_is_extreme = bool(atr_v and atr_avg and atr_v > EXTREME_MULT * atr_avg)

                if current_is_extreme:
                    log.info(f"⚠ Giorno estremo (ATR={atr_v:.2f} > {EXTREME_MULT}x avg={atr_avg:.2f}) — skip H1")
                else:
                    can, reason = state.can_trade(now_utc)
                    if not can:
                        log.debug(f"Trade non permesso: {reason}")
                    elif count_open_positions() >= 2:
                        log.debug(f"Max posizioni aperte (2)")
                    else:
                        # ── Segnale primario H1 ───────────────────────────────
                        hour = bar_dt.hour
                        strategy_name, direction = get_signal(I_h1, i_h1, hour, current_regime)

                        if strategy_name is None:
                            log.info(f"Regime: {current_regime} | Nessun segnale primario H1 su {bar_dt.strftime('%H:%M')}")
                        elif has_position_in_direction(direction):
                            log.debug(f"[H1] Direzione {direction} già occupata, skip {strategy_name}")
                        else:
                            params = STRATEGY_PARAMS[strategy_name]
                            atr_i = I_h1['atr'][i_h1] if I_h1['atr'][i_h1] else None
                            if rm:
                                rp = rm.get_order_params(
                                    ai_score=last_ai_score, atr=atr_i,
                                    strategy=strategy_name, direction=direction,
                                    atr_avg=I_h1['atr_avg'][i_h1],
                                    adx=I_h1['adx'][i_h1], dip=I_h1['dip'][i_h1],
                                    dim=I_h1['dim'][i_h1], hour_utc=bar_dt.hour
                                )
                                if rp.get('paused'):
                                    log.info(f"⛔ SEGNALE H1 SOSPESO (manipolazione/spike) | manip_mult=0")
                                    rp = None
                            if rm and rp:
                                lot_use, tp_use, sl_use = rp['lot'], rp['tp_usd'], rp['sl_usd']
                                log.info(
                                    f"★ SEGNALE H1: {direction.upper()} | {params['label']} | Regime: {current_regime} "
                                    f"| ADX={I_h1['adx'][i_h1]:.1f} | RSI={I_h1['rsi'][i_h1]:.1f} "
                                    f"| score={last_ai_score:.0f} | {rp['tier_label']} manip={rp['manip_mult']:.2f} "
                                    f"| lot={lot_use} | TP=${tp_use} | SL=${sl_use} "
                                    f"| BE@+${rp['be_trigger']} | TS step=${rp['ts_step']}"
                                )
                            elif not rm:
                                lot_use = LOT_SIZE
                                tp_use  = params['tp_usd'] if isinstance(params['tp_usd'], float) else 20.0
                                sl_use  = params['sl_usd'] if isinstance(params['sl_usd'], float) else 12.0
                                rp = None
                                log.info(
                                    f"★ SEGNALE H1: {direction.upper()} | {params['label']} | Regime: {current_regime} "
                                    f"| ADX={I_h1['adx'][i_h1]:.1f} | RSI={I_h1['rsi'][i_h1]:.1f} "
                                    f"| TP=${tp_use} SL=${sl_use}"
                                )
                            else:
                                continue  # paused — skip order
                            result = place_order(direction, tp_use, sl_use, strategy_name, lot_size=lot_use)
                            if result:
                                # Registra BE trigger nel RiskManager per questo ticket
                                if rm and rp and 'be_trigger' in rp:
                                    rm._pos_state[result.order] = {
                                        'be_done': False,
                                        'partial_done': False,
                                        'ts_price': None,
                                        'ts_step': rp.get('ts_step', 5.0),
                                        'be_trigger': rp['be_trigger']
                                    }
                                
                                tick = mt5.symbol_info_tick(SYMBOL)
                                price = tick.ask if direction=='buy' else tick.bid if tick else 0
                                log_trade_to_json(direction, strategy_name, price,
                                                  round(price+(tp_use if direction=='buy' else -tp_use),2),
                                                  round(price-(sl_use if direction=='buy' else -sl_use),2), result)
                                state.record_trade(0, now_utc)
                                acc = get_account_info()
                                if acc:
                                    log.info(f"Account aggiornato: {acc['equity']:.2f} {acc['currency']}")
                                sync_to_vercel(
                                    acc, get_open_positions_data(), get_recent_trades_data(200),
                                    {'running':True,'dry_run':DRY_RUN,'symbol':SYMBOL,'lot':LOT_SIZE,
                                     'trades_today':state.trades_today,'pnl_today':state.pnl_today,
                                     'regime':current_regime,'last_signal':strategy_name}
                                )
                                last_sync_time = time.time()

                        # ── Secondary H1 strategies ───────────────────────────
                        for (sec_id, sec_tf, sec_dir_filter) in REGIME_MULTI_STRATEGIES.get(current_regime, []):
                            if sec_tf != 'H1': continue
                            if sec_id == strategy_name: continue   # già provata come primaria
                            if count_open_positions() >= 2: break
                            if state.trades_today >= MAX_TRADES: break
                            fn2 = SIGNAL_FNS.get(sec_id)
                            if not fn2: continue
                            
                            # Supporto per session hour se richiesto
                            if sec_id == 'S10_ST_MACD_SESSION':
                                sec_dir = fn2(I_h1, i_h1, hour)
                            else:
                                sec_dir = fn2(I_h1, i_h1)
                            if not sec_dir: continue
                            if sec_dir_filter and sec_dir != sec_dir_filter: continue
                            if has_position_in_direction(sec_dir): continue
                            sec_params = STRATEGY_PARAMS.get(sec_id, {})
                            atr_i2 = I_h1['atr'][i_h1] if I_h1['atr'][i_h1] else None
                            rp2 = None
                            if rm:
                                rp2 = rm.get_order_params(
                                    ai_score=last_ai_score, atr=atr_i2, strategy=sec_id, direction=sec_dir,
                                    atr_avg=I_h1['atr_avg'][i_h1], adx=I_h1['adx'][i_h1],
                                    dip=I_h1['dip'][i_h1], dim=I_h1['dim'][i_h1], hour_utc=bar_dt.hour
                                )
                                if rp2.get('paused'):
                                    log.info(f"⛔ SEGNALE H1 (sec) SOSPESO (manipolazione) | {sec_id}")
                                    continue
                                lot2, tp2, sl2 = rp2['lot'], rp2['tp_usd'], rp2['sl_usd']
                                log.info(f"★ SEGNALE H1 (sec): {sec_dir.upper()} | {sec_params.get('label',sec_id)} | {rp2['tier_label']} manip={rp2['manip_mult']:.2f} | lot={lot2} | TP=${tp2} | SL=${sl2}")
                            else:
                                lot2, tp2, sl2 = LOT_SIZE, 20.0, 12.0
                                log.info(f"★ SEGNALE H1 (sec): {sec_dir.upper()} | {sec_params.get('label',sec_id)}")
                            result2 = place_order(sec_dir, tp2, sl2, sec_id, lot_size=lot2)
                            if result2:
                                tick2 = mt5.symbol_info_tick(SYMBOL)
                                price2 = tick2.ask if sec_dir=='buy' else tick2.bid if tick2 else 0
                                log_trade_to_json(sec_dir, sec_id, price2,
                                                  round(price2+(tp2 if sec_dir=='buy' else -tp2),2),
                                                  round(price2-(sl2 if sec_dir=='buy' else -sl2),2), result2)
                                state.record_trade(0, now_utc)

            # ── Controlla nuova candela M15 (es. S01_EXHAUSTION in TREND_DOWN) ─
            pb_entry = PLAYBOOK.get(current_regime, {})
            if pb_entry.get('tf') == 'M15' and not current_is_extreme:
                candles_m15 = get_candles_tf('M15', 450)
                if candles_m15 and len(candles_m15) >= 50:
                    latest_m15 = candles_m15[-2]['t']
                    if latest_m15 != last_bar_time_m15:
                        last_bar_time_m15 = latest_m15
                        bar_dt_m15 = datetime.datetime.fromtimestamp(latest_m15, tz=datetime.timezone.utc)
                        log.info(f"─── Nuova barra M15 chiusa: {bar_dt_m15.strftime('%Y-%m-%d %H:%M')} UTC ───")
                        can, reason = state.can_trade(now_utc)
                        if not can:
                            log.debug(f"[M15] Trade non permesso: {reason}")
                        elif count_open_positions() >= 2:
                            log.debug(f"[M15] Max posizioni aperte (2)")
                        else:
                            I_m15 = compute_indicators(candles_m15)
                            idx = len(candles_m15) - 2
                            sname = pb_entry['strategy']
                            sf = SESSION_FILTER.get(sname)
                            if sf and bar_dt_m15.hour in sf['block_hours']:
                                log.info(f"[M15] {sname} saltato — sessione asiatica ({bar_dt_m15.strftime('%H:%M')} UTC)")
                                continue
                            fn    = SIGNAL_FNS.get(sname)

                            # Calcolo trend H1 corrente per confluenza
                            curr_h1_trend = I_h1['st'][i_h1] if 'st' in I_h1 else 0

                            if sname == 'S16_GOLDEN_SQUEEZE':
                                direction = fn(I_m15, idx, h1_trend=curr_h1_trend)
                            else:
                                direction = fn(I_m15, idx) if fn else None
                                
                            if direction and has_position_in_direction(direction):
                                log.debug(f"[M15] Direzione {direction} già occupata, skip {sname}")
                            elif direction:
                                params = STRATEGY_PARAMS[sname]
                                atr_i = I_m15['atr'][idx] if I_m15['atr'][idx] else None
                                rp = None
                                if rm:
                                    rp = rm.get_order_params(
                                        ai_score=last_ai_score, atr=atr_i, strategy=sname, direction=direction,
                                        atr_avg=I_m15.get('atr_avg', [None]*len(candles_m15))[idx],
                                        adx=I_m15['adx'][idx], dip=I_m15['dip'][idx],
                                        dim=I_m15['dim'][idx], hour_utc=bar_dt_m15.hour
                                    )
                                    if rp.get('paused'):
                                        log.info(f"⛔ SEGNALE M15 SOSPESO (manipolazione) | {sname}")
                                        rp = None
                                if rp:
                                    lot_use, tp_use, sl_use = rp['lot'], rp['tp_usd'], rp['sl_usd']
                                    log.info(f"★ SEGNALE M15: {direction.upper()} | {params['label']} | Regime: {current_regime} | {rp['tier_label']} manip={rp['manip_mult']:.2f} | lot={lot_use} | TP=${tp_use} | SL=${sl_use}")
                                elif not rm:
                                    lot_use, tp_use, sl_use = LOT_SIZE, 15.0, 10.0
                                    log.info(f"★ SEGNALE M15: {direction.upper()} | {params['label']} | Regime: {current_regime}")
                                else:
                                    continue  # paused
                                result = place_order(direction, tp_use, sl_use, sname, lot_size=lot_use)
                                if result:
                                    tick = mt5.symbol_info_tick(SYMBOL)
                                    price = tick.ask if direction=='buy' else tick.bid if tick else 0
                                    log_trade_to_json(direction, sname, price,
                                                      round(price+(tp_use if direction=='buy' else -tp_use),2),
                                                      round(price-(sl_use if direction=='buy' else -sl_use),2), result)
                                    state.record_trade(0, now_utc)
                                    acc = get_account_info()
                                    if acc: log.info(f"Account aggiornato: {acc['equity']:.2f} {acc['currency']}")
                                    sync_to_vercel(acc, get_open_positions_data(), get_recent_trades_data(200),
                                                   {'running':True,'dry_run':DRY_RUN,'symbol':SYMBOL,'lot':LOT_SIZE,
                                                    'trades_today':state.trades_today,'pnl_today':state.pnl_today,
                                                    'regime':current_regime,'last_signal':sname})
                                    last_sync_time = time.time()
                            else:
                                log.info(f"[M15] Regime: {current_regime} | Nessun segnale su {bar_dt_m15.strftime('%H:%M')}")

            # ── Controlla nuova candela M30 (es. S09 in WEAK/VOLATILE) ──────────
            elif pb_entry.get('tf') == 'M30' and not current_is_extreme:
                candles_m30 = get_candles_tf('M30', 450)
                if candles_m30 and len(candles_m30) >= 50:
                    latest_m30 = candles_m30[-2]['t']
                    if latest_m30 != last_bar_time_m30:
                        last_bar_time_m30 = latest_m30
                        bar_dt_m30 = datetime.datetime.fromtimestamp(latest_m30, tz=datetime.timezone.utc)
                        log.info(f"─── Nuova barra M30 chiusa: {bar_dt_m30.strftime('%Y-%m-%d %H:%M')} UTC ───")
                        can, reason = state.can_trade(now_utc)
                        if not can:
                            log.debug(f"[M30] Trade non permesso: {reason}")
                        elif count_open_positions() >= 2:
                            log.debug(f"[M30] Max posizioni aperte (2)")
                        else:
                            I_m30 = compute_indicators(candles_m30)
                            idx = len(candles_m30) - 2
                            sname = pb_entry['strategy']
                            sf = SESSION_FILTER.get(sname)
                            if sf and bar_dt_m30.hour in sf['block_hours']:
                                log.info(f"[M30] {sname} saltato — sessione asiatica ({bar_dt_m30.strftime('%H:%M')} UTC)")
                                continue
                            fn    = SIGNAL_FNS.get(sname)
                            direction = fn(I_m30, idx) if fn else None
                            if direction and has_position_in_direction(direction):
                                log.debug(f"[M30] Direzione {direction} già occupata, skip {sname}")
                            elif direction:
                                params = STRATEGY_PARAMS[sname]
                                atr_i = I_m30['atr'][idx] if I_m30['atr'][idx] else None
                                rp = None
                                if rm:
                                    rp = rm.get_order_params(
                                        ai_score=last_ai_score, atr=atr_i, strategy=sname, direction=direction,
                                        atr_avg=I_m30.get('atr_avg', [None]*len(candles_m30))[idx],
                                        adx=I_m30['adx'][idx], dip=I_m30['dip'][idx],
                                        dim=I_m30['dim'][idx], hour_utc=bar_dt_m30.hour
                                    )
                                    if rp.get('paused'):
                                        log.info(f"⛔ SEGNALE M30 SOSPESO (manipolazione) | {sname}")
                                        rp = None
                                if rp:
                                    lot_use, tp_use, sl_use = rp['lot'], rp['tp_usd'], rp['sl_usd']
                                    log.info(f"★ SEGNALE M30: {direction.upper()} | {params['label']} | Regime: {current_regime} | {rp['tier_label']} manip={rp['manip_mult']:.2f} | lot={lot_use} | TP=${tp_use} | SL=${sl_use}")
                                elif not rm:
                                    lot_use, tp_use, sl_use = LOT_SIZE, 15.0, 10.0
                                    log.info(f"★ SEGNALE M30: {direction.upper()} | {params['label']} | Regime: {current_regime}")
                                else:
                                    continue  # paused
                                result = place_order(direction, tp_use, sl_use, sname, lot_size=lot_use)
                                if result:
                                    tick = mt5.symbol_info_tick(SYMBOL)
                                    price = tick.ask if direction=='buy' else tick.bid if tick else 0
                                    log_trade_to_json(direction, sname, price,
                                                      round(price+(tp_use if direction=='buy' else -tp_use),2),
                                                      round(price-(sl_use if direction=='buy' else -sl_use),2), result)
                                    state.record_trade(0, now_utc)
                                    acc = get_account_info()
                                    if acc: log.info(f"Account aggiornato: {acc['equity']:.2f} {acc['currency']}")
                                    sync_to_vercel(acc, get_open_positions_data(), get_recent_trades_data(200),
                                                   {'running':True,'dry_run':DRY_RUN,'symbol':SYMBOL,'lot':LOT_SIZE,
                                                    'trades_today':state.trades_today,'pnl_today':state.pnl_today,
                                                    'regime':current_regime,'last_signal':sname})
                                    last_sync_time = time.time()
                            else:
                                log.info(f"[M30] Regime: {current_regime} | Nessun segnale su {bar_dt_m30.strftime('%H:%M')}")

            time.sleep(CHECK_SEC)

        except KeyboardInterrupt:
            log.info("Bot fermato dall'utente (Ctrl+C)")
            break
        except Exception as e:
            log.error(f"Errore imprevisto: {e}", exc_info=True)
            time.sleep(60)

    mt5.shutdown()
    log.info("MT5 disconnesso. Bot terminato.")

if __name__ == '__main__':
    run()
