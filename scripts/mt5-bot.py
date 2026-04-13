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

# ── CONFIGURAZIONE ────────────────────────────────────────────────────────────
MT5_LOGIN    = 1301224666
MT5_PASSWORD = "Alessandro95!"
MT5_SERVER   = "XMGlobal-MT5 6"

SYMBOL       = "GOLD"
LOT_SIZE     = 0.02          # lot size iniziale (0.02 = sicuro su €1000)
MAGIC        = 20250413      # ID univoco per gli ordini di questo bot
MAX_TRADES   = 10            # max operazioni per giorno (richiesto 10)
COOLDOWN_H   = 0.5           # ore di cooldown tra trade (30 min per più frequenza)
EXTREME_MULT = 3.5           # ATR > 3.5x avg = giorno estremo, skip
SESSION_UTC  = (0, 24)       # Finestra 24h per massimizzare profitti (come richiesto)
CHECK_SEC    = 3             # Polling ultra-rapido (3 secondi)

# ── VERCEL SYNC (mostra dati live nella UI) ───────────────────────────────────
VERCEL_URL   = "https://tradeflow-ai-delta.vercel.app"
MT5_SECRET   = "tradeflow-mt5-secret"              # deve combaciare con MT5_BOT_SECRET su Vercel
SYNC_ENABLED = True          # False per disabilitare il sync cloud

LOG_FILE     = "mt5-bot.log"

# ── TP/SL per strategia (in punti/pips su XAUUSD) ───────────────────────────
# Su XAUUSD spot: 1 punto = $0.01, quindi TP=$15 → 1500 punti
# In mt5: XAUUSD ha digits=2, quindi 1 punto = 0.01
# Usiamo valori in dollari, converti in punti al momento dell'ordine
STRATEGY_PARAMS = {
    'S01_EXHAUSTION':  {'tp_usd': 15.0, 'sl_usd':  9.0, 'label': 'Exhaustion'},
    'S06_ORDERBLOCK':  {'tp_usd': 18.0, 'sl_usd': 10.0, 'label': 'Order Block'},
    'S09_VWAP_WPR':    {'tp_usd': 18.0, 'sl_usd': 10.0, 'label': 'VWAP+W%R'},
    'S12_WPR_KELTNER': {'tp_usd': 20.0, 'sl_usd': 12.0, 'label': 'W%R+Keltner'},
    'S10_SESSION_MOM': {'tp_usd': 20.0, 'sl_usd': 12.0, 'label': 'Session Mom'},
}
REGIME_PRIORITY = {
    'TREND_UP':   ['S01_EXHAUSTION','S06_ORDERBLOCK','S10_SESSION_MOM'],
    'TREND_DOWN': ['S01_EXHAUSTION','S06_ORDERBLOCK','S10_SESSION_MOM'],
    'WEAK_UP':    ['S06_ORDERBLOCK','S10_SESSION_MOM','S12_WPR_KELTNER'],
    'WEAK_DOWN':  ['S06_ORDERBLOCK','S10_SESSION_MOM','S12_WPR_KELTNER'],
    'RANGE':      ['S09_VWAP_WPR','S12_WPR_KELTNER','S06_ORDERBLOCK'],
    'VOLATILE':   ['S12_WPR_KELTNER','S09_VWAP_WPR'],
    'UNKNOWN':    ['S10_SESSION_MOM'],
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

# ── COMPUTE INDICATORS ────────────────────────────────────────────────────────
def compute_indicators(candles):
    H=[c['h'] for c in candles]
    L=[c['l'] for c in candles]
    C=[c['c'] for c in candles]
    V=[c['v'] for c in candles]
    n=len(C)
    I={}
    I['C']=C; I['H']=H; I['L']=L
    I['e20']=ema(C,20); I['e50']=ema(C,50)
    I['e100']=ema(C,100); I['e200']=ema(C,200)
    I['rsi']=rsi(C,14)
    I['atr']=atr(H,L,C,14)
    I['adx'],I['dip'],I['dim']=adx_calc(H,L,C,14)
    I['ml'],I['ms'],I['mh']=macd(C,12,26,9)
    I['bb_mid'],I['bb_up'],I['bb_dn']=bb(C,20,2.0)
    I['wpr']=wpr(H,L,C,14)
    I['km'],I['ku'],I['kl']=keltner(H,L,C,20,2.0)
    I['vwap']=vwap_intraday(candles)
    I['obv']=obv(C,V)
    I['obv_ema']=ema(I['obv'],20)
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

# ── STRATEGY SIGNALS ─────────────────────────────────────────────────────────
def signal_exhaustion(I, i):
    """S01: Exhaustion — ADX forte + DI spread + MACD contra-trend"""
    if i < 50: return None
    adx_v=I['adx'][i]; dip=I['dip'][i]; dim=I['dim'][i]
    mh=I['mh'][i]; mhp=I['mh'][i-1]
    r=I['rsi'][i]
    if None in (adx_v,mh,mhp,r): return None
    if adx_v < 25: return None
    spread = abs(dip-dim)
    if spread < 12: return None
    # BUY exhaustion (trend down, MACD gira su)
    if dim > dip and mhp < 0 and mh > mhp and r < 45:
        return 'buy'
    # SELL exhaustion (trend up, MACD gira giù)
    if dip > dim and mhp > 0 and mh < mhp and r > 55:
        return 'sell'
    return None

def signal_orderblock(I, i):
    """S06: Order Block — rimbalzo su zone istituzionali"""
    if i < 50: return None
    C=I['C']; H=I['H']; L=I['L']
    e20=I['e20'][i]; e50=I['e50'][i]
    r=I['rsi'][i]; mh=I['mh'][i]
    if None in (e20,e50,r,mh): return None
    # trova ultimo swing high/low (order block)
    swing_lo = min(L[i-10:i])
    swing_hi = max(H[i-10:i])
    dist_lo = (C[i]-swing_lo)/C[i]
    dist_hi = (swing_hi-C[i])/C[i]
    if dist_lo < 0.0015 and C[i] > e20 and r < 50 and mh > 0:
        return 'buy'
    if dist_hi < 0.0015 and C[i] < e20 and r > 50 and mh < 0:
        return 'sell'
    return None

def signal_vwap_wpr(I, i):
    """S09: VWAP + W%R"""
    if i < 30: return None
    v=I['vwap'][i]; w=I['wpr'][i]; mh=I['mh'][i]
    C=I['C'][i]
    if None in (v,w,mh): return None
    if C > v and w < -80 and mh > 0: return 'buy'
    if C < v and w > -20 and mh < 0: return 'sell'
    return None

def signal_wpr_keltner(I, i):
    """S12: W%R + Keltner"""
    if i < 30: return None
    w=I['wpr'][i]; ku=I['ku'][i]; kl=I['kl'][i]; km=I['km'][i]
    r=I['rsi'][i]
    if None in (w,ku,kl,r): return None
    if w < -80 and I['C'][i] < kl and r < 40: return 'buy'
    if w > -20 and I['C'][i] > ku and r > 60: return 'sell'
    return None

def signal_session_mom(I, i, hour):
    """S10: Session Momentum — London open"""
    if i < 50: return None
    if hour not in range(7, 12): return None
    e20=I['e20'][i]; e50=I['e50'][i]; mh=I['mh'][i]; mhp=I['mh'][i-1]
    r=I['rsi'][i]; C=I['C'][i]
    if None in (e20,e50,mh,mhp,r): return None
    if C>e20>e50 and mhp<0 and mh>=0 and r>45: return 'buy'
    if C<e20<e50 and mhp>0 and mh<=0 and r<55: return 'sell'
    return None

SIGNAL_FNS = {
    'S01_EXHAUSTION':  signal_exhaustion,
    'S06_ORDERBLOCK':  signal_orderblock,
    'S09_VWAP_WPR':    signal_vwap_wpr,
    'S12_WPR_KELTNER': signal_wpr_keltner,
    'S10_SESSION_MOM': signal_session_mom,
}

def get_signal(I, i, hour, regime):
    """Restituisce (strategia, direzione) basandosi sul regime corrente"""
    priority = REGIME_PRIORITY.get(regime, ['S10_SESSION_MOM'])
    for sname in priority:
        fn = SIGNAL_FNS.get(sname)
        if fn is None: continue
        if sname == 'S10_SESSION_MOM':
            direction = fn(I, i, hour)
        else:
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

def place_order(direction, tp_usd, sl_usd, strategy_name):
    """Invia un ordine market su MT5"""
    tick = mt5.symbol_info_tick(SYMBOL)
    sym_info = mt5.symbol_info(SYMBOL)
    if tick is None or sym_info is None:
        log.error("Impossibile ottenere tick/info simbolo")
        return None

    # Calcola TP/SL in prezzo
    point = sym_info.point          # di solito 0.01 per XAUUSD
    digits = sym_info.digits

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
        "volume":    LOT_SIZE,
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
        log.info(f"[DRY-RUN] Ordine simulato: {direction.upper()} {LOT_SIZE} {SYMBOL} "
                 f"@ {price:.2f}  TP={tp_price:.2f}  SL={sl_price:.2f}  [{strategy_name}]")
        return {'retcode': 10009, 'simulated': True}

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log.error(f"Ordine fallito: retcode={result.retcode} — {result.comment}")
        return None
    log.info(f"✓ Ordine eseguito: #{result.order} {direction.upper()} {LOT_SIZE} {SYMBOL} "
             f"@ {price:.2f}  TP={tp_price:.2f}  SL={sl_price:.2f}  [{strategy_name}]")
    return result

def manage_positions():
    """Gestisce Break Even e Trailing Stop per le posizioni aperte"""
    positions = mt5.positions_get(symbol=SYMBOL)
    if positions is None: return

    tick = mt5.symbol_info_tick(SYMBOL)
    sym_info = mt5.symbol_info(SYMBOL)
    if not tick or not sym_info: return

    for p in positions:
        if p.magic != MAGIC: continue
        
        entry = p.price_open
        current = p.price_current
        sl = p.sl
        tp = p.tp
        initial_risk = abs(entry - sl) if sl != 0 else 10.0 # fallback $10
        
        # Calcolo distanza attuale dal profitto in prezzo
        profit_dist = (current - entry) if p.type == mt5.POSITION_TYPE_BUY else (entry - current)
        
        new_sl = None

        # 1. BREAK EVEN (BE): se profitto >= 0.8x rischio iniziale, sposta SL a entry + mini profit
        if profit_dist >= initial_risk * 0.8:
            be_level = entry + (sym_info.point * 20) if p.type == mt5.POSITION_TYPE_BUY else entry - (sym_info.point * 20)
            # Sposta solo se non è già a BE o meglio
            if p.type == mt5.POSITION_TYPE_BUY and (sl < entry):
                new_sl = be_level
            elif p.type == mt5.POSITION_TYPE_SELL and (sl > entry or sl == 0):
                new_sl = be_level

        # 2. TRAILING STOP (TS): se profitto >= 1.2x rischio iniziale, attiva trailing
        if profit_dist >= initial_risk * 1.2:
            trail_dist = initial_risk * 0.7 # distanza del trailing
            if p.type == mt5.POSITION_TYPE_BUY:
                potential_ts = current - trail_dist
                if potential_ts > sl: 
                    new_sl = potential_ts
            else:
                potential_ts = current + trail_dist
                if sl == 0 or potential_ts < sl:
                    new_sl = potential_ts

        if new_sl and abs(new_sl - sl) > (sym_info.point * 5): 
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "symbol": SYMBOL,
                "position": p.ticket,
                "sl": round(new_sl, sym_info.digits),
                "tp": tp,
            }
            res = mt5.order_send(request)
            if res.retcode == mt5.TRADE_RETCODE_DONE:
                log.info(f"🛡️ MODIFICA SL (BE/TS): Ticket {p.ticket} -> SL @ {new_sl:.2f}")

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

def get_recent_trades_data(n=20):
    """Legge gli ultimi N trade da mt5-trades.json"""
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

def fetch_remote_commands():
    """Interroga il DB per nuovi comandi dalla UI"""
    if not SYNC_ENABLED or not VERCEL_URL: return None
    payload = json.dumps({
        'action': 'mt5_command_get',
        'secret': MT5_SECRET
    }).encode('utf-8')
    try:
        req = urllib.request.Request(
            f"{VERCEL_URL}/api/db",
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            if r.status == 200:
                data = json.loads(r.read().decode('utf-8'))
                return data.get('command')
    except Exception as e:
        log.debug(f"Fetch comandi fallito: {e}")
    return None

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
    last_sync_time = 0    # timestamp ultimo sync Vercel
    last_cmd_check = 0    # timestamp ultimo check comandi

    while True:
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            now_ts = time.time()

            # ── 1. Gestione Posizioni Aperte (BE/TS) ─────────────────────────
            manage_positions()

            # ── 2. Verifica Comandi Remoti (ogni CHECK_SEC) ─────────────────
            if now_ts - last_cmd_check >= CHECK_SEC:
                cmd = fetch_remote_commands()
                if cmd:
                    log.info(f"🚀 RICEVUTO COMANDO REMOTO: {cmd['direction'].upper()} su {cmd['strategy']}")
                    # Verifica scadenza (3 minuti)
                    created = datetime.datetime.fromisoformat(cmd['created_at'].replace('Z', '+00:00'))
                    if (now_utc - created).total_seconds() > 180:
                        log.warning("⚠️ Comando scaduto (>3min), ignorato.")
                    else:
                        # Esegui ordine
                        result = place_order(cmd['direction'], cmd['tp'], cmd['sl'], cmd['strategy'])
                        if result:
                            # Log e Sync immediato (opzionale, già fatto in place_order + sync_to_vercel)
                            pass
                last_cmd_check = now_ts

            # ── 3. Recupera candele per analisi autonoma ─────────────────────
            candles = get_candles(300)
            if candles is None or len(candles) < 100:
                log.warning("Candele non disponibili, riprovo...")
                time.sleep(10)
                continue

            # ── Sync periodico a Vercel (ogni CHECK_SEC) ──────
            if now_ts - last_sync_time >= CHECK_SEC:
                acc_data = get_account_info()
                positions_data = get_open_positions_data()
                trades_data = get_recent_trades_data(20)
                
                # Calcola regime attuale se abbiamo le candele
                current_regime = 'UNKNOWN'
                if 'I' in locals() and 'i' in locals():
                    current_regime = detect_regime(I, i)

                bot_status = {
                    'running': True,
                    'dry_run': DRY_RUN,
                    'symbol': SYMBOL,
                    'lot': LOT_SIZE,
                    'trades_today': state.trades_today,
                    'pnl_today': round(state.pnl_today, 2),
                    'regime': current_regime,
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

            # ── Regime ───────────────────────────────────────────────────────
            regime = detect_regime(I, i)

            # ── Controllo giorno estremo ──────────────────────────────────────
            atr_v   = I['atr'][i]
            atr_avg = I['atr_avg'][i]
            if atr_v and atr_avg and atr_v > EXTREME_MULT * atr_avg:
                log.info(f"⚠ Giorno estremo (ATR={atr_v:.2f} > {EXTREME_MULT}x avg={atr_avg:.2f}) — skip")
                time.sleep(10) # Ciclo più breve per reattività comandi
                continue

            # ── Controllo sessione e limiti giornalieri ───────────────────────
            can, reason = state.can_trade(now_utc)
            if not can:
                log.debug(f"Trade non permesso: {reason}")
                time.sleep(10) # Ciclo più breve per reattività comandi
                continue

            # ── Controlla posizioni aperte ────────────────────────────────────
            open_pos = count_open_positions()
            if open_pos > 0:
                log.debug(f"Posizione già aperta ({open_pos}), attendo chiusura")
                time.sleep(10) # Ciclo più breve per reattività comandi
                continue

            # ── Segnale strategia ─────────────────────────────────────────────
            hour = bar_dt.hour
            strategy_name, direction = get_signal(I, i, hour, regime)

            if strategy_name is None:
                log.info(f"Regime: {regime} | Nessun segnale su {bar_dt.strftime('%H:%M')}")
                time.sleep(10) # Ciclo più breve per reattività comandi
                continue

            # ── Calcolo TP/SL Dinamico (ATR-based) ──────────────────────────
            atr_v = I['atr'][i]
            # Multiplier: 2.0x ATR per TP, 1.0x ATR per SL (come config strat)
            # Se la strategia ha parametri fissi (S01, S06, etc. in STRATEGY_PARAMS), 
            # usiamo quelli come minimo, o l'ATR se maggiore.
            min_tp = STRATEGY_PARAMS[strategy_name]['tp_usd']
            min_sl = STRATEGY_PARAMS[strategy_name]['sl_usd']
            
            calc_tp = round(atr_v * 2.0, 2) if atr_v else min_tp
            calc_sl = round(atr_v * 1.0, 2) if atr_v else min_sl
            
            # Applica protezioni
            final_tp = max(min_tp, calc_tp)
            final_sl = max(min_sl, calc_sl)

            log.info(f"★ SEGNALE: {direction.upper()} | {strategy_name} | Regime: {regime} "
                     f"| ADX={I['adx'][i]:.1f} | RSI={I['rsi'][i]:.1f} "
                     f"| TP=${final_tp} SL=${final_sl} (ATR-based)")

            # ── Invia ordine ──────────────────────────────────────────────────
            result = place_order(direction, final_tp, final_sl, strategy_name)

            if result:
                tick = mt5.symbol_info_tick(SYMBOL)
                price = tick.ask if direction=='buy' else tick.bid if tick else 0
                log_trade_to_json(direction, strategy_name, price,
                                  price + (params['tp_usd'] if direction=='buy' else -params['tp_usd']),
                                  price - (params['sl_usd'] if direction=='buy' else -params['sl_usd']),
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

            time.sleep(10) # Ciclo più breve per reattività comandi

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
