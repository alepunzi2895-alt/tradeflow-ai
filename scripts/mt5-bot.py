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
import sys, io, time, json, math, datetime, argparse, os, logging, urllib.request, urllib.error
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ── RISK MANAGER ─────────────────────────────────────────────────────────────
try:
    from risk_manager import get_risk_manager, RiskManager
except ImportError:
    get_risk_manager = None
    log_placeholder = logging.getLogger('tf-bot')
    log_placeholder.warning("risk_manager.py non trovato — uso lot size fisso")

# ── CONFIGURAZIONE ────────────────────────────────────────────────────────────
MT5_LOGIN    = 1301224666
MT5_PASSWORD = "Alessandro95!"
MT5_SERVER   = "XMGlobal-MT5 6"

SYMBOL       = "GOLD"
LOT_SIZE     = 0.02          # lot size iniziale (0.02 = sicuro su €1000)
MAGIC        = 20250413      # ID univoco per gli ordini di questo bot
MAX_TRADES   = 3             # max operazioni per giorno
COOLDOWN_H   = 1             # ore di cooldown tra trade
EXTREME_MULT = 3.0           # ATR > 3x avg = giorno estremo, skip
SESSION_UTC  = (7, 17)       # finestra operativa London+NY (UTC)
CHECK_SEC    = 60            # polling ogni 60 secondi

VERCEL_URL   = "https://tradeflow-ai-delta.vercel.app"  # NO slash finale
MT5_SECRET   = "tradeflow-mt5-secret"              # deve combaciare con MT5_BOT_SECRET su Vercel
SYNC_ENABLED = True          # False per disabilitare il sync cloud


LOG_FILE     = "mt5-bot.log"

# ── TP/SL per strategia ───────────────────────────────────────────────────────
# GOLD su XM: 1 punto = $0.01 (digits=2). TP=$20 → 2000 punti.
# 2 strategie MFKK attive post-backtest MT5 2026-04-14
STRATEGY_PARAMS = {
    'S00_MFKK':          {'tp_usd': 20.0,  'sl_usd': 12.0,  'label': 'MFKK Score'},
    'S05_MFKK_INTRADAY': {'tp_usd': 'ATR', 'sl_usd': 'ATR', 'label': 'MFKK Intraday'},
}
# Allineato con strategy.js regimePriority (aggiornato 2026-04-14)
REGIME_PRIORITY = {
    'TREND_UP':   ['S00_MFKK', 'S05_MFKK_INTRADAY'],
    'TREND_DOWN': ['S00_MFKK', 'S05_MFKK_INTRADAY'],
    'WEAK_UP':    ['S00_MFKK', 'S05_MFKK_INTRADAY'],
    'WEAK_DOWN':  ['S00_MFKK', 'S05_MFKK_INTRADAY'],
    'RANGE':      ['S05_MFKK_INTRADAY', 'S00_MFKK'],
    'VOLATILE':   ['S05_MFKK_INTRADAY', 'S00_MFKK'],
    'UNKNOWN':    ['S00_MFKK'],
}

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

# ── COMPUTE INDICATORS ────────────────────────────────────────────────────────
def compute_indicators(candles):
    H=[c['h'] for c in candles]
    L=[c['l'] for c in candles]
    C=[c['c'] for c in candles]
    V=[c['v'] for c in candles]
    n=len(C)
    I={}
    I['C']=C; I['H']=H; I['L']=L; I['V']=V
    I['e20']=ema(C,20); I['e50']=ema(C,50)
    I['e100']=ema(C,100); I['e200']=ema(C,200)
    I['rsi']=rsi(C,14)
    I['atr']=atr(H,L,C,14)
    I['adx'],I['dip'],I['dim']=adx_calc(H,L,C,14)
    I['ml'],I['ms'],I['mh']=macd(C,12,26,9)
    I['cci']=cci(H,L,C,50)
    I['mom']=mom(C,10)
    I['bb_mid'],I['bb_up'],I['bb_dn']=bb(C,20,2.0)
    I['wpr']=wpr(H,L,C,14)
    I['km'],I['ku'],I['kl']=keltner(H,L,C,20,2.0)
    I['vwap']=vwap_intraday(candles)
    I['obv']=obv(C,V)
    I['obv_ema']=ema(I['obv'],20)
    # OBV MACD T-Channel per S05_MFKK_INTRADAY
    try:
        _, _, I['obv_oc'] = obv_macd_tchannel(H,L,C,V)
    except Exception:
        I['obv_oc'] = [0]*n
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

# ── STRATEGY SIGNALS (2 STRATEGIE UFFICIALI) ─────────────────────────────────
def signal_mfkk_score(I, i):
    """
    S00_MFKK — MFKK Score ponderato (identico a strategy.js)
    Score = 80% ADX + 10% MACD + 10% CCI
    BUY se score_bull >= 90 | SELL se score_bear >= 75
    """
    if i < 50: return None
    a=I['adx'][i]; dp=I['dip'][i]; dm=I['dim'][i]
    m=I['ml'][i]; c=I['cci'][i] if I['cci'][i] is not None else 0
    if None in (a, dp, dm, m): return None

    bull = bear = 0.0
    adx_c = min(a/40*100, 100)
    if dm > dp: bear += adx_c*0.80
    else:       bull += adx_c*0.80

    ms = min(abs(m)/0.5*100, 100)
    if m >= 0: bull += ms*0.10
    else:      bear += ms*0.10

    cs = min(abs(c)/100*100, 100)
    if c >= 0: bull += cs*0.10
    else:      bear += cs*0.10

    if bull >= 90: return 'buy'
    if bear >= 75: return 'sell'
    return None

def signal_mfkk_intraday(I, i):
    """
    S05_MFKK_INTRADAY — V2 Triple MACD (identico a strategy.js)
    OBV T-Channel direzione + RSI + MACD line + Momentum + ADX >= 20
    """
    if i < 2: return None
    oc  = I.get('obv_oc', [])
    if not oc or i >= len(oc): return None
    r   = I['rsi'][i]
    mo  = I['mom'][i]
    a   = I['adx'][i]
    mc  = I['ml'][i]   # MACD line
    if None in (r, mo, a, mc): return None
    if a < 20: return None
    if oc[i] == 1  and r > 50 and mo > 0 and mc > 0: return 'buy'
    if oc[i] == -1 and r < 50 and mo < 0 and mc < 0: return 'sell'
    return None

SIGNAL_FNS = {
    'S00_MFKK':          signal_mfkk_score,
    'S05_MFKK_INTRADAY': signal_mfkk_intraday,
}

def get_signal(I, i, hour, regime):
    """Restituisce (strategia, direzione) basandosi sul regime corrente"""
    priority = REGIME_PRIORITY.get(regime, ['S00_MFKK'])
    for sname in priority:
        fn = SIGNAL_FNS.get(sname)
        if fn is None: continue
        direction = fn(I, i)
        if direction:
            return sname, direction
    return None, None

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
        if self.trades_today >= MAX_TRADES:
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

def get_candles(n=300):
    """Recupera le ultime N candele H1 da MT5"""
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, n)
    if rates is None or len(rates) == 0:
        return None
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
        from_date = datetime.datetime.now(utc) - datetime.timedelta(days=60)
        to_date   = datetime.datetime.now(utc)
        deals = mt5.history_deals_get(from_date, to_date)
        if deals is not None and len(deals) > 0:
            result = []
            for d in sorted(deals, key=lambda x: x.time, reverse=True):
                if d.entry != 1: continue   # solo deal di chiusura (exit)
                result.append({
                    'ticket':    d.ticket,
                    'time':      datetime.datetime.fromtimestamp(d.time, tz=utc).isoformat(),
                    'direction': 'buy' if d.type == 0 else 'sell',
                    'strategy':  d.comment.replace('TF-AI ', '') if d.comment else 'N/A',
                    'price':     round(d.price, 2),
                    'profit':    round(d.profit, 2),
                    'volume':    d.volume,
                })
                if len(result) >= n: break
            if result:
                log.debug(f"🎯 Recuperati {len(result)} deal dallo storico MT5")
                return result
    except Exception as e:
        log.debug(f"MT5 history_deals fallback su JSON: {e}")
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
        with urllib.request.urlopen(req, timeout=10) as r:
            if r.status == 200:
                log.debug("Sync Vercel OK")
    except Exception as e:
        log.debug(f"Sync Vercel fallito (non critico): {e}")

# ── LOOP PRINCIPALE ───────────────────────────────────────────────────────────
def run():
    log.info("="*60)
    log.info("TradeFlow AI — MT5 Bot avviato")
    log.info(f"Symbol: {SYMBOL} | Lot: {LOT_SIZE} | Max trade/gg: {MAX_TRADES}")
    log.info(f"Dry-run: {DRY_RUN}")
    log.info("="*60)

    if not mt5_connect():
        log.error("Connessione MT5 fallita. Assicurati che MT5 sia aperto e configurato.")
        sys.exit(1)

    acc = get_account_info()
    if acc:
        log.info(f"Account: {acc['balance']:.2f} {acc['currency']} "
                 f"(equity={acc['equity']:.2f}, free margin={acc['margin_free']:.2f})")

    last_bar_time = None   # per rilevare nuova candela H1
    last_sync_time = -999  # forza sync immediato al primo ciclo
    last_ai_score  = 50.0  # default neutro
    last_score_ts  = 0     # timestamp ultimo fetch score

    # Inizializza RiskManager
    rm = get_risk_manager(base_lot=LOT_SIZE, max_lot=LOT_SIZE*5) if get_risk_manager else None
    if rm:
        log.info(f"RiskManager attivo — base_lot={LOT_SIZE} max_lot={LOT_SIZE*5}")
    else:
        log.warning("RiskManager disabilitato — uso lot size fisso")

    while True:
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc)

            # ── Recupera candele ──────────────────────────────────────────────
            candles = get_candles(300)
            if candles is None or len(candles) < 100:
                log.warning("Candele non disponibili, riprovo...")
                time.sleep(30)
                continue

            # ── Sync periodico a Vercel (ogni 20s) + fetch AI score ────────
            now_ts = time.time()
            if now_ts - last_sync_time >= 20:
                # Verifica connessione MT5 — riconnetti se persa
                if mt5.account_info() is None:
                    log.warning("MT5 connessione persa — tentativo riconnessione...")
                    mt5.shutdown()
                    time.sleep(5)
                    if not mt5_connect():
                        log.error("Riconnessione MT5 fallita, riprovo in 30s")
                        time.sleep(30)
                        continue
                    log.info("MT5 riconnesso correttamente.")

            # ── Fetch AI Score ogni 60s ────────────────────────────────────
            if rm and (now_ts - last_score_ts) >= 60:
                last_ai_score = RiskManager.fetch_ai_score(VERCEL_URL)
                last_score_ts = now_ts
                log.info(f"🧠 AI Score aggiornato: {last_ai_score:.1f} — tier: {rm.get_tier(last_ai_score)['label']}")

                acc_data = get_account_info()
                positions_data = get_open_positions_data()
                trades_data = get_recent_trades_data(20)
                bot_status = {
                    'running': True,
                    'dry_run': DRY_RUN,
                    'symbol': SYMBOL,
                    'lot': LOT_SIZE,
                    'trades_today': state.trades_today,
                    'pnl_today': round(state.pnl_today, 2),
                    'regime': 'UNKNOWN',
                    'last_bar': datetime.datetime.fromtimestamp(last_bar_time, tz=datetime.timezone.utc).isoformat() if last_bar_time else None,
                }
                sync_to_vercel(acc_data, positions_data, trades_data, bot_status)
                last_sync_time = now_ts

            # ── Controlla nuova candela H1 ────────────────────────────────────
            latest_bar_time = candles[-2]['t']   # -2 = ultima barra chiusa
            if latest_bar_time == last_bar_time:
                # Nessuna nuova barra chiusa, aspetta
                time.sleep(CHECK_SEC)
                continue
            last_bar_time = latest_bar_time
            bar_dt = datetime.datetime.fromtimestamp(latest_bar_time, tz=datetime.timezone.utc)
            log.info(f"─── Nuova barra H1 chiusa: {bar_dt.strftime('%Y-%m-%d %H:%M')} UTC ───")

            # ── Calcola indicatori ────────────────────────────────────────────
            I = compute_indicators(candles)
            i = len(candles) - 2   # ultima barra chiusa

            # ── Gestione posizioni: BE + Trailing + Parziali ──────────────────
            if rm:
                atr_now = I['atr'][i] if I['atr'][i] else 10.0
                rm.manage_positions(mt5, SYMBOL, MAGIC, atr_now)

            # ── Regime ───────────────────────────────────────────────────────
            regime = detect_regime(I, i)

            # ── Controllo giorno estremo ──────────────────────────────────────
            atr_v   = I['atr'][i]
            atr_avg = I['atr_avg'][i]
            if atr_v and atr_avg and atr_v > EXTREME_MULT * atr_avg:
                log.info(f"⚠ Giorno estremo (ATR={atr_v:.2f} > {EXTREME_MULT}x avg={atr_avg:.2f}) — skip")
                time.sleep(CHECK_SEC)
                continue

            # ── Controllo sessione e limiti giornalieri ───────────────────────
            can, reason = state.can_trade(now_utc)
            if not can:
                log.debug(f"Trade non permesso: {reason}")
                time.sleep(CHECK_SEC)
                continue

            # ── Controlla posizioni aperte ────────────────────────────────────
            open_pos = count_open_positions()
            if open_pos > 0:
                log.debug(f"Posizione già aperta ({open_pos}), attendo chiusura")
                time.sleep(CHECK_SEC)
                continue

            # ── Segnale strategia ─────────────────────────────────────────────
            hour = bar_dt.hour
            strategy_name, direction = get_signal(I, i, hour, regime)

            if strategy_name is None:
                log.info(f"Regime: {regime} | Nessun segnale su {bar_dt.strftime('%H:%M')}")
                time.sleep(CHECK_SEC)
                continue

            params = STRATEGY_PARAMS[strategy_name]

            # ── Calcola parametri adattativi con RiskManager ──────────────────
            atr_i = I['atr'][i] if I['atr'][i] else None
            if rm:
                rp = rm.get_order_params(
                    ai_score=last_ai_score,
                    atr=atr_i,
                    strategy=strategy_name,
                    direction=direction
                )
                lot_use = rp['lot']
                tp_use  = rp['tp_usd']
                sl_use  = rp['sl_usd']
                log.info(
                    f"★ SEGNALE: {direction.upper()} | {params['label']} | Regime: {regime} "
                    f"| ADX={I['adx'][i]:.1f} | RSI={I['rsi'][i]:.1f} "
                    f"| score={last_ai_score:.0f} | {rp['tier_label']} "
                    f"| lot={lot_use} | TP=${tp_use} | SL=${sl_use} "
                    f"| BE@+${rp['be_trigger']} | TS step=${rp['ts_step']}"
                )
            else:
                lot_use = LOT_SIZE
                tp_use  = params['tp_usd'] if isinstance(params['tp_usd'], float) else 20.0
                sl_use  = params['sl_usd'] if isinstance(params['sl_usd'], float) else 12.0
                log.info(
                    f"★ SEGNALE: {direction.upper()} | {params['label']} | Regime: {regime} "
                    f"| ADX={I['adx'][i]:.1f} | RSI={I['rsi'][i]:.1f} "
                    f"| TP=${tp_use} SL=${sl_use}"
                )

            # ── Invia ordine ────────────────────────────────────────
            result = place_order(direction, tp_use, sl_use, strategy_name, lot_size=lot_use)

            if result:
                tick = mt5.symbol_info_tick(SYMBOL)
                price = tick.ask if direction=='buy' else tick.bid if tick else 0
                log_trade_to_json(direction, strategy_name, price,
                                  round(price + (tp_use if direction=='buy' else -tp_use), 2),
                                  round(price - (sl_use if direction=='buy' else -sl_use), 2),
                                  result)
                state.record_trade(0, now_utc)  # PnL reale verrà da MT5
                acc = get_account_info()
                if acc:
                    log.info(f"Account aggiornato: {acc['equity']:.2f} {acc['currency']}")
                # Sync immediato dopo trade
                sync_to_vercel(
                    acc, get_open_positions_data(), get_recent_trades_data(20),
                    {'running':True,'dry_run':DRY_RUN,'symbol':SYMBOL,'lot':LOT_SIZE,
                     'trades_today':state.trades_today,'pnl_today':state.pnl_today,
                     'regime':regime,'last_signal':strategy_name}
                )
                last_sync_time = time.time()

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
