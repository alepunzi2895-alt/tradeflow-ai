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
    signal_range_reversal,
    signal_fib_confluence, fib_confluence_trade_levels,
    signal_dow_dip, DOW_DIP_TP_ATR, DOW_DIP_SL_ATR, DOW_DIP_MAX_BARS,
)

# ── RISK MANAGER (legacy, kept for backward compat) ───────────────────────────
try:
    from risk_manager import get_risk_manager, RiskManager
except ImportError:
    get_risk_manager = None
    log_placeholder = logging.getLogger('tf-bot')
    log_placeholder.warning("risk_manager.py non trovato — uso lot size fisso")

# ── RISK GUARDIAN (mandatory — bot non parte senza) ──────────────────────────
from risk_guardian import get_risk_guardian, RiskGuardian

# ── STRATEGY SELECTOR AGENT ───────────────────────────────────────────────────
try:
    from strategy_selector import StrategySelector, is_hard_blocked
except ImportError:
    StrategySelector = None
    def is_hard_blocked(strategy_id):
        return False
    log_placeholder3 = logging.getLogger('tf-bot')
    log_placeholder3.warning("strategy_selector.py non trovato — uso playbook statico")

# ── KEY LEVELS AGENT ──────────────────────────────────────────────────────────
try:
    from key_levels import get_key_levels_agent, KeyLevelsAgent
except ImportError:
    get_key_levels_agent = None
    KeyLevelsAgent = None
    log_placeholder4 = logging.getLogger('tf-bot')
    log_placeholder4.warning("key_levels.py non trovato — TP/SL non verranno aggiustati")

# ── PERFORMANCE TRACKER (self-learning) ───────────────────────────────────────
try:
    from performance_tracker import get_performance_tracker
except ImportError:
    get_performance_tracker = None
    log_placeholder5 = logging.getLogger('tf-bot')
    log_placeholder5.warning("performance_tracker.py non trovato — self-learning disabilitato")

# ── NEWS GUARDIAN ─────────────────────────────────────────────────────────────
try:
    from news_guardian import get_news_guardian
except ImportError:
    get_news_guardian = None
    log_placeholder6 = logging.getLogger('tf-bot')
    log_placeholder6.warning("news_guardian.py non trovato — pausa news disabilitata")

# ── CONFIGURAZIONE (Legacy fallback, ora legge da .env) ───────────────
MT5_LOGIN    = int(os.getenv("MT5_LOGIN", 1301224666))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "Alessandro95!")
MT5_SERVER   = os.getenv("MT5_SERVER", "XMGlobal-MT5 6")

SYMBOL       = os.getenv("SYMBOL", "GOLD")

LOT_SIZE     = 0.02          # lot size base conto $1000 — CONSERVATIVE→0.01, NORMAL→0.02, AGGRESSIVE→0.03
MAGIC        = 20250413      # ID univoco per gli ordini di questo bot
MAX_TRADES   = 0             # 0 = nessun limite giornaliero
COOLDOWN_H   = 0             # ore di cooldown tra trade (0 = gestito da max 1 per strategia)
MAX_OPEN_ORDERS = 2          # max 2 posizioni contemporanee (ridotto da 6 per contenere esposizione)
SL_COOLDOWN_H   = 3          # ore di pausa globale dopo 2 SL consecutivi (era 1h)
STRATEGY_SL_COOLDOWN_H = 4   # ore di pausa per singola strategia dopo 2 SL (era 2h)
EXTREME_MULT = 3.0           # ATR > 3x avg = giorno estremo, skip
MIN_COMPOSITE_TO_TRADE = 45  # composite score minimo per aprire — soglia abbassata per aumentare frequenza trade

# ── IN-MEMORY ORDER TRACKING (resiliente a race condition MT5) ────────────────
# Aggiornato immediatamente dopo place_order(), eliminato alla chiusura posizione
# Formato: {strategy_name: (order_ticket, direction_str)}  ex: {'S16_GOLDEN_SQUEEZE': (12345, 'sell')}
# order_ticket = result.order da mt5.order_send() = position ticket in hedging mode
_strategy_order_tickets: dict = {}  # {strategy_name: (ticket, direction)}
SESSION_UTC  = (0, 24)       # operativo 24h — pausa gestita solo da NewsGuardian (-2h/+2h attorno a news HIGH)
CHECK_SEC    = 10            # polling ogni 10 secondi

# ── S20_FIB_CONFLUENCE — integrata nel flusso normale (promossa da isolata 2026-09-01) ──
# Sizing via RiskGuardian (composite score/tier/compounding) con UNICA eccezione:
# lotto finale ×2 rispetto al lot RiskGuardian standard (edge validato ma più raro,
# eq. al vecchio lotto fisso 0.03 vs base_lot 0.02). Partecipa ai cooldown SL condivisi
# (globale + per-strategia), a MAX_OPEN_ORDERS e alla guardia di correlazione direzionale.
# Gestione posizione resta un mini-manager proprio (SL strutturale + TP hard 2R; a TP1/1R
# chiude S20_PARTIAL_LOT e sposta lo SL del residuo a BE) — non generica RiskGuardian,
# perché l'edge backtestato (OOS PF 1.72) dipende da questa lifecycle specifica.
S20_ENABLED     = True
S20_LOT         = 0.03      # fallback se RiskGuardian non disponibile
S20_LOT_MULT    = 2.0       # unica eccezione RiskGuardian per S20: lotto finale ×2
S20_CONFIDENCE  = 0.55      # strategy_confidence proxy — OOS PF 1.72/WR~52%, edge debole ma reale
S20_AI_SCORE_PROXY = 55.0   # nessun AI scorer nativo per il segnale M5 Fib Confluence
S20_PARTIAL_LOT = 0.02      # chiuso a TP1 (residuo 0.01 runner → TP2 / BE)
S20_TAG         = 'S20_FIB_CONFLUENCE'
S20_COOLDOWN_MIN = 120      # min tra due ingressi S20 (allineato al backtest)
S20_STATE_FILE  = os.path.join(os.path.dirname(__file__), '..', 'data', 's20_live_state.json')
_s20_state: dict = {}       # {ticket(str): {dir, entry, risk, tp1, tp2, be_done}}
_s20_last_bar = None
_s20_last_entry_ts = 0.0

# ── S30_DOW_DIP — US30 mean-reversion, blocco ISOLATO su 2° simbolo (2026-09-03) ──
# Connors RSI(2) long-only su H4 (ricerca: scripts/us30_harness.py — full PF 1.63 /
# holdout PF 2.09 / 4-4 fold walk-forward). Completamente separato dal flusso XAU:
# simbolo proprio (US30Cash), niente StrategySelector/playbook/RiskGuardian/compounding,
# non conta in MAX_OPEN_ORDERS GOLD. Exit: SL/TP hard ATR-based lasciati a MT5 +
# time-stop. Fase iniziale: lotto fisso minimo, come fece S20 (paper→0.03→scala).
US30_ENABLED     = True
US30_SYMBOL_CANDIDATES = ["US30Cash", "US30", "US30.cash", "DJ30", "WS30", "US30m", "US30.spot"]
US30_SYMBOL      = None                       # risolto a startup
US30_TAG         = 'S30_DOW_DIP'
US30_LOT         = 0.10                       # vol_min US30Cash; fisso in fase small-size
US30_TP_ATR      = DOW_DIP_TP_ATR             # 1.2
US30_SL_ATR      = DOW_DIP_SL_ATR             # 2.6
US30_MAX_BARS    = DOW_DIP_MAX_BARS           # 18 barre H4 (~3 gg) → time-stop
US30_COOLDOWN_H  = 4                          # ore min tra due ingressi
US30_STATE_FILE  = os.path.join(os.path.dirname(__file__), '..', 'data', 'us30_live_state.json')
_us30_state: dict = {}                        # {ticket(str): {entry, sl, tp, open_ts}}
_us30_last_bar = None
_us30_last_entry_ts = 0.0

# Se sei su VPS Standalone, usa http://localhost:3000
VERCEL_URL   = os.getenv("VERCEL_URL", "https://tradeflow-ai-delta.vercel.app") 
MT5_SECRET   = os.getenv("MT5_BOT_SECRET", "tradeflow-mt5-secret") 

SYNC_ENABLED = True          # False per disabilitare il sync cloud

current_ai_score = 50.0      # Global per rilassamento filtri


def _local_ai_score(consecutive_sl: int, today_pnl: float = 0.0) -> float:
    """
    Fallback AI Score calcolato localmente quando Vercel non è raggiungibile.
    Abbassa il tier del RiskGuardian in base a serie di SL consecutivi,
    garantendo che il sistema riduca il rischio anche offline.
      0 SL + pnl ok → 55 (NORMAL stabile)
      1 SL           → 44 (NORMAL borderline)
      2 SL           → 32 (CONSERVATIVE)
      3+ SL          → 20 (CONSERVATIVE profondo)
      pnl < -100     → max 44 anche senza SL
    """
    if consecutive_sl >= 3:
        return 20.0
    if consecutive_sl == 2:
        return 32.0
    if consecutive_sl == 1:
        return 44.0
    if today_pnl < -100:
        return 44.0
    return 55.0


LOG_FILE     = "mt5-bot.log"
AI_SCORE_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'ai_score_history.json')


def _append_ai_score_history(score: float, source: str, tier: str,
                              composite: float = None, regime: str = None) -> None:
    """Appende una entry a data/ai_score_history.json. Mantiene gli ultimi 30 giorni."""
    entry: dict = {
        'ts':     datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'score':  round(score, 1),
        'tier':   tier,
        'source': source,
    }
    if composite is not None:
        entry['composite'] = round(composite, 1)
    if regime is not None:
        entry['regime'] = regime
    try:
        path = AI_SCORE_HISTORY_FILE
        history: list = []
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as _f:
                history = json.load(_f)
        history.append(entry)
        cutoff = (datetime.datetime.now(datetime.timezone.utc) -
                  datetime.timedelta(days=30)).strftime('%Y-%m-%dT')
        history = [e for e in history if e.get('ts', '') >= cutoff]
        with open(path, 'w', encoding='utf-8') as _f:
            json.dump(history, _f, separators=(',', ':'))
    except Exception as _e:
        logging.getLogger('tf-bot').debug(f"[ai_history] {_e}")


# ── TP/SL per strategia ───────────────────────────────────────────────────────
# GOLD su XM: digits=2 → 1 punto prezzo = $1 per 0.01 lot.
# tp_usd / sl_usd qui sono distanze in punti prezzo (non dollari assoluti).
# Es. ATR≈9.5 pt × tp_mult=2.0 → tp_use=19.0 → price ± 19.0 → ~$19 per 0.01 lot.
STRATEGY_PARAMS = {
    'S05_MFKK_INTRADAY':   {'tp_usd': 'ATR', 'sl_usd': 'ATR', 'label': 'MFKK Intraday V3', 'tp_mult': 3.5, 'sl_mult': 1.5},
    'S09_MFKK_SCALPING':   {'tp_usd': 'ATR', 'sl_usd': 'ATR', 'label': 'MFKK Scalping V2', 'tp_mult': 4.0, 'sl_mult': 1.5},
    'S10_OB_FVG_SCALP':    {'tp_usd': 'ATR', 'sl_usd': 'ATR', 'label': 'OB+FVG Scalp V2', 'tp_mult': 3.5, 'sl_mult': 1.5},
    'S16_GOLDEN_SQUEEZE':  {'tp_usd': 'ATR', 'sl_usd': 'ATR', 'label': 'Golden Squeeze V3', 'tp_mult': 3.5, 'sl_mult': 2.0, 'be_mult': 1.3},
    'S17_CONVERGENCE_SCALP': {'tp_usd': 'ATR', 'sl_usd': 'ATR', 'label': 'Convergence Scalp V2', 'tp_mult': 4.0, 'sl_mult': 1.75},  # sprint 2026-09-02: 1.5→1.75
    'S00_MFKK':            {'tp_usd': 'ATR', 'sl_usd': 'ATR', 'label': 'MFKK Core V2', 'tp_mult': 3.5, 'sl_mult': 1.5},
    'S18_RANGE_REVERSAL':  {'tp_usd': 'ATR', 'sl_usd': 'ATR', 'label': 'Range Reversal V1', 'tp_mult': 2.0, 'sl_mult': 1.2},
    # S20 non passa da questo dict (SL/TP propri, strutturali via fib_confluence_trade_levels,
    # non ATR-mult) — mult qui allineati a risk_guardian.py::STRATEGY_ATR_PARAMS solo per
    # coerenza col check pre-commit (usati unicamente dal risk-cap 2% interno a _calc_lot).
    'S20_FIB_CONFLUENCE':  {'tp_usd': 'ATR', 'sl_usd': 'ATR', 'label': 'Fib Confluence V2', 'tp_mult': 1.0, 'sl_mult': 1.0},
}

# Playbook caricato da regime_playbook.json al boot; fallback hardcoded
PLAYBOOK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'regime_playbook.json')
FALLBACK_PLAYBOOK = {
    'TREND_UP':   {'strategy': 'S16_GOLDEN_SQUEEZE',   'tf': 'H1'},  # S05 H1 WR 25% → S16 H1 WR 51%
    'TREND_DOWN': {'strategy': 'S16_GOLDEN_SQUEEZE',   'tf': 'H1'},  # S05 H1 PF 1.046 → S16 H1 PF 2.12
    'WEAK_UP':    {'strategy': 'S10_OB_FVG_SCALP',     'tf': 'M30'},
    'WEAK_DOWN':  {'strategy': 'S10_OB_FVG_SCALP',     'tf': 'M30'},
    'VOLATILE':   {'strategy': 'S09_MFKK_SCALPING',    'tf': 'M30'},
    'RANGE':      {'strategy': 'S10_OB_FVG_SCALP',     'tf': 'M30'},
    'UNKNOWN':    {'strategy': 'S10_OB_FVG_SCALP',     'tf': 'M30'},
}
PLAYBOOK = FALLBACK_PLAYBOOK  # verrà sovrascritta da load_playbook()

# ── LOGGING ───────────────────────────────────────────────────────────────────
class _RingBufferHandler(logging.Handler):
    """Keeps the last N log records in memory for UI sync."""
    def __init__(self, capacity=30):
        super().__init__()
        from collections import deque
        self._buf = deque(maxlen=capacity)
    def emit(self, record):
        import datetime as _dt
        self._buf.append({
            'ts':  _dt.datetime.fromtimestamp(record.created).strftime('%H:%M:%S'),
            'lvl': record.levelname,
            'msg': record.getMessage(),
        })
    def get_lines(self):
        return list(self._buf)

_ring_handler = _RingBufferHandler(capacity=30)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
        _ring_handler,
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

def cci_standard(src, p=50):
    n = len(src); out = [None] * n
    if n < p: return out
    for i in range(p - 1, n):
        sl = src[i - p + 1 : i + 1]
        mn = sum(sl) / p
        md = sum(abs(x - mn) for x in sl) / p
        out[i] = (src[i] - mn) / (0.015 * md) if md != 0 else 0
    return out

def stochastic(src, p=14):
    n = len(src); out = [None] * n
    for i in range(p - 1, n):
        sl = [x for x in src[i - p + 1 : i + 1] if x is not None]
        if len(sl) < p: continue
        lo = min(sl); hi = max(sl)
        out[i] = ((src[i] - lo) / (hi - lo) * 100) if hi > lo else 50
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

# bb() defined once below (removed duplicate — see BUG#4 fix 2026-04-23)

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
    # CCI_S: CCI(50) -> stochastic(50) -> SMA(8) -> SMA(8)
    cci_tmp = cci_standard(C, 50)
    stk_tmp = stochastic(cci_tmp, 50)
    stk_k = sma([x if x is not None else 50 for x in stk_tmp], 8)
    I['cci'] = sma([x if x is not None else 50 for x in stk_k], 8)
    I['mom']=mom(C,10)
    I['bb_mid'],I['bb_up'],I['bb_dn']=bb(C,20,2.0)
    I['wpr']=wpr(H,L,C,14)
    I['km'],I['ku'],I['kl']=keltner(H,L,C,20,2.0)
    I['vwap']=vwap_intraday(candles)
    I['obv']=obv(C,V)
    I['obv_ema']=ema(I['obv'],20)
    I['srsi_k'],I['srsi_d']=stoch_rsi(C,14,14,3,3)  # fix: stoch_p=14 (era 3 → troppo reattivo)
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
    if adx_v >= 18:
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
    'S18_RANGE_REVERSAL':   signal_range_reversal,
}

# Session filter: S16 skip 0-7 UTC (Asia low vol); S00 skip 0-6 UTC (noise)
SESSION_FILTER = {
    'S16_GOLDEN_SQUEEZE': {'block_hours': range(0, 8)},
    'S00_MFKK':           {'block_hours': range(0, 7)},
    'S18_RANGE_REVERSAL': {'block_hours': range(0, 7)},
}

# Multi-strategy map: (strategy_id, tf, direction_filter) per regime
# Priorities based on adaptive backtest: S10 PF 1.79 > S16 PF 1.29 in WEAK; S10 2nd in TREND
# S17 only on H4 (PF 1.71); S09 only in RANGE/VOLATILE (PF 1.65 M30)
REGIME_MULTI_STRATEGIES = {
    # S05 rimosso da H1 (backtest H1: PF 1.046 WR 25% — drag sul sistema); S16 H1 diventa primario secondario
    'TREND_UP':   [('S16_GOLDEN_SQUEEZE','H1',None), ('S10_OB_FVG_SCALP','M30',None), ('S17_CONVERGENCE_SCALP','H4',None)],
    'TREND_DOWN': [('S16_GOLDEN_SQUEEZE','H1',None), ('S10_OB_FVG_SCALP','M30',None), ('S17_CONVERGENCE_SCALP','H4',None)],
    'WEAK_UP':    [('S10_OB_FVG_SCALP','M30',None), ('S18_RANGE_REVERSAL','M30',None), ('S00_MFKK','M30',None), ('S09_MFKK_SCALPING','M30',None), ('S17_CONVERGENCE_SCALP','H4',None)],
    'WEAK_DOWN':  [('S10_OB_FVG_SCALP','M30',None), ('S18_RANGE_REVERSAL','M30',None), ('S00_MFKK','M30',None), ('S09_MFKK_SCALPING','M30',None), ('S17_CONVERGENCE_SCALP','H4',None)],
    'VOLATILE':   [('S09_MFKK_SCALPING','M30',None), ('S10_OB_FVG_SCALP','M30',None), ('S17_CONVERGENCE_SCALP','H4',None)],
    'RANGE':      [('S18_RANGE_REVERSAL','M30',None), ('S10_OB_FVG_SCALP','M30',None), ('S09_MFKK_SCALPING','M30',None), ('S00_MFKK','M30',None), ('S17_CONVERGENCE_SCALP','H4',None)],
    'UNKNOWN':    [('S18_RANGE_REVERSAL','M30',None), ('S10_OB_FVG_SCALP','M30',None), ('S00_MFKK','M30',None), ('S17_CONVERGENCE_SCALP','H4',None)],
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
    elif sname == 'S16_GOLDEN_SQUEEZE':
        # Fix 2026-09-02: passare `hour` (+ h1_trend proxy) — senza `hour` il filtro
        # sessione interno 7-18 UTC era bypassato e S16 tradava 24/7 su H1 (bot 76 trade
        # vs backtester 15 sulla stessa finestra live). Allinea il bot al backtester.
        direction = fn(I, i, h1_trend=I['st'][i] if I.get('st') else None, hour=hour)
    elif sname == 'S00_MFKK':
        # Fix 2026-09-02: passare `hour` e `tf='H1'` — senza `hour` il ramo SELL di S00 è
        # strutturalmente impossibile (`is_london_ny` = False → sell_thr resta 999) e la
        # finestra 7-22 UTC è bypassata; senza `tf` buy_di_min = 20 (valore M30) invece di 15.
        # get_signal serve S00 solo su H1 (return None per tf != 'H1'). S00 resta hard-blocked
        # in strategy_overrides.json — fix di correttezza, neutrale finché il blocco è attivo.
        direction = fn(I, i, hour=hour, tf='H1')
    else:
        direction = fn(I, i)
    return (sname, direction) if direction else (None, None)

def quality_gate(strategy_id, direction, I, i):
    """Return True if trade passes additional quality checks."""
    # 0. Self-learning hard block (data/strategy_overrides.json, score_mult=0.0).
    # Prima del 2026-09-01 questo override era letto SOLO da StrategySelector —
    # i playbook statici (REGIME_MULTI_STRATEGIES M30/H1-secondary) lo ignoravano
    # e continuavano a tradare strategie "bloccate" (vedi 07_self_learning_log.md).
    if is_hard_blocked(strategy_id):
        return False

    atr_v = I['atr'][i]
    atr_avg = I['atr_avg'][i]

    # 1. No trade during ATR spikes (news/chaos)
    if atr_v and atr_avg and atr_v > 2.0 * atr_avg:
        return False

    # 2. Require minimum spread DI for trending strategies
    if strategy_id in ('S16_GOLDEN_SQUEEZE', 'S05_MFKK_INTRADAY'):
        dip, dim = I['dip'][i], I['dim'][i]
        if dip is not None and dim is not None and abs(dip - dim) < 8:
            return False

    # 3. RSI extremes only block TRUE exhaustion (85/15 not 75/25).
    # XAU/USD RSI > 75 è normale in un mercato bull forte — soglia 75 bloccava
    # tutti i buy durante trend rialzisti prolungati. Signal functions gestiscono RSI internamente.
    rsi_v = I['rsi'][i]
    if rsi_v:
        if direction == 'buy'  and rsi_v > 85: return False
        if direction == 'sell' and rsi_v < 15: return False

    return True

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
    """Conta le posizioni aperte del bot. Source of truth: MT5; in-memory come lower-bound."""
    if DRY_RUN:
        return sum(1 for t, _ in _strategy_order_tickets.values() if t)
    mt5_count = sum(1 for p in (mt5.positions_get(symbol=SYMBOL) or []) if p.magic == MAGIC)
    # len(_strategy_order_tickets) è il numero di strategie con ticket — utile solo se MT5 è lento
    return max(mt5_count, len(_strategy_order_tickets))

def has_position_in_direction(direction):
    """True se esiste già una posizione nella direzione specificata.
    Controlla in-memory PRIMA di MT5 per essere immune a latenza post-place_order."""
    # 1. In-memory check: cattura posizioni appena aperte non ancora visibili in MT5
    for _ticket, _dir in _strategy_order_tickets.values():
        if _ticket and _dir == direction:  # _ticket valido (evita entry dry-run corrotte)
            return True
    if DRY_RUN:
        return False  # in dry-run non ci sono posizioni MT5 reali, usa solo in-memory
    # 2. MT5 check: verità assoluta quando in-memory è vuoto o desincronizzato
    for p in mt5.positions_get(symbol=SYMBOL) or []:
        if p.magic != MAGIC: continue
        if direction == 'buy'  and p.type == mt5.ORDER_TYPE_BUY:  return True
        if direction == 'sell' and p.type == mt5.ORDER_TYPE_SELL: return True
    return False

def has_open_position_for_strategy(strategy_name):
    """True se esiste già un ordine aperto per questa strategia."""
    target_comment = f"TF-AI {strategy_name}"
    positions = mt5.positions_get(symbol=SYMBOL) or []
    # Comment scan è il check primario: source of truth indipendente dal ticket
    for p in positions:
        if p.magic == MAGIC and (p.comment or '') == target_comment:
            _dir_fb = 'buy' if p.type == mt5.ORDER_TYPE_BUY else 'sell'
            _strategy_order_tickets[strategy_name] = (p.ticket, _dir_fb)
            return True
    # Ticket fallback: copre la finestra tra place_order() e visibilità in MT5
    if strategy_name in _strategy_order_tickets:
        order_ticket, _dir = _strategy_order_tickets[strategy_name]
        if not order_ticket:
            # ticket invalido (es. dry-run con ticket non assegnato): pulisci
            _strategy_order_tickets.pop(strategy_name, None)
            return False
        # In dry-run non ci sono posizioni MT5 reali: basta che il ticket sia in memoria
        if DRY_RUN:
            return True
        if any(p.ticket == order_ticket and p.magic == MAGIC for p in positions):
            return True
        # positions_get() vuoto = possibile race condition (posizione appena aperta,
        # non ancora visibile in MT5). Tieni il ticket in memoria e ritorna True
        # per evitare doppio ordine. Il cleanup avviene solo dalla position monitoring.
        if not positions:
            return True
        # MT5 ha restituito posizioni ma questa non c'è → chiusa davvero
        _strategy_order_tickets.pop(strategy_name, None)
    return False

def place_order(direction, tp_usd, sl_usd, strategy_name, lot_size=None,
                key_levels_result=None, atr=None):
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

    # ── KEY LEVELS: snap TP before strong levels, move SL beyond liquidity ──
    if key_levels_result and get_key_levels_agent and atr:
        try:
            kla = get_key_levels_agent()
            adj = kla.adjust_tp_sl(
                key_levels_result, price, direction,
                tp_price, sl_price, atr
            )
            tp_price = round(adj["tp_price"], digits)
            sl_price = round(adj["sl_price"], digits)
            if adj.get("partial_targets"):
                targets_str = ", ".join(f"{t['price']:.2f}({t['type']})"
                                        for t in adj["partial_targets"][:3])
                log.info(f"🎯 Partial targets [{strategy_name}]: {targets_str}")
        except Exception as e:
            log.warning(f"[KeyLevels] adjust_tp_sl error: {e}")

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
        import random
        _dry_ticket = random.randint(100000, 999999)
        log.info(f"[DRY-RUN] Ordine simulato: {direction.upper()} {lot} {SYMBOL} "
                 f"@ {price:.2f}  TP={tp_price:.2f}  SL={sl_price:.2f}  [{strategy_name}] ticket={_dry_ticket}")
        # Restituisce un oggetto-like con .order per compatibilità con getattr(result, 'order', 0)
        class _DryResult:
            retcode = 10009
            order = _dry_ticket
            simulated = True
        return _DryResult()

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

# ── S20_FIB_CONFLUENCE — M5, sizing RiskGuardian (entry + gestione parziale) ─
def _s20_load_state():
    global _s20_state
    try:
        if os.path.exists(S20_STATE_FILE):
            with open(S20_STATE_FILE, encoding='utf-8') as f:
                _s20_state = {int(k): v for k, v in json.load(f).items()}
    except Exception as e:
        log.warning(f"[S20] load state: {e}")

def _s20_save_state():
    try:
        with open(S20_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump({str(k): v for k, v in _s20_state.items()}, f, indent=2)
    except Exception as e:
        log.warning(f"[S20] save state: {e}")

def s20_rebuild_from_open():
    """Al riavvio: riadotta eventuali posizioni S20 aperte non ancora tracciate (be_done ignoto)."""
    if not S20_ENABLED:
        return
    for p in (mt5.positions_get(symbol=SYMBOL) or []):
        if p.magic != MAGIC or not (p.comment and 'S20' in p.comment) or p.ticket in _s20_state:
            continue
        d = 'buy' if p.type == 0 else 'sell'
        risk = abs(p.price_open - p.sl) if p.sl else None
        _s20_state[p.ticket] = {'dir': d, 'entry': p.price_open, 'risk': risk,
                                'tp1': None, 'tp2': p.tp or None, 'be_done': None}
        _strategy_order_tickets[S20_TAG] = (p.ticket, d)
        log.info(f"[S20] posizione riadottata al riavvio: #{p.ticket} {d} @ {p.price_open}")
    if _s20_state:
        _s20_save_state()

def s20_manage():
    """Posizioni S20 aperte: al raggiungimento di TP1 (1R) chiude S20_PARTIAL_LOT e sposta lo SL a BE."""
    if not S20_ENABLED or not _s20_state:
        return
    open_pos = {p.ticket: p for p in (mt5.positions_get(symbol=SYMBOL) or []) if p.magic == MAGIC}
    tick = mt5.symbol_info_tick(SYMBOL)
    for ticket in list(_s20_state.keys()):
        st = _s20_state[ticket]
        p = open_pos.get(ticket)
        if p is None:                                   # chiusa (TP2 / SL / BE)
            _s20_state.pop(ticket, None); _s20_save_state()
            log.info(f"[S20] posizione #{ticket} chiusa")
            continue
        if st.get('be_done') in (True, None) or not st.get('risk') or st.get('tp1') is None or tick is None:
            continue
        px = tick.bid if st['dir'] == 'buy' else tick.ask
        if not ((st['dir'] == 'buy' and px >= st['tp1']) or (st['dir'] == 'sell' and px <= st['tp1'])):
            continue
        vol = round(min(S20_PARTIAL_LOT, max(p.volume - 0.01, 0.0)), 2)
        if vol < 0.01:
            st['be_done'] = True; _s20_save_state(); continue
        if DRY_RUN:
            log.info(f"[S20][DRY] TP1 raggiunto → parziale {vol} + SL→BE  #{ticket}")
            st['be_done'] = True; _s20_save_state(); continue
        close_type = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
        cprice = tick.bid if p.type == 0 else tick.ask
        r1 = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": vol,
                             "type": close_type, "position": ticket, "price": cprice, "deviation": 20,
                             "magic": MAGIC, "comment": "TF-AI S20 partial",
                             "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC})
        if not r1 or r1.retcode != mt5.TRADE_RETCODE_DONE:
            log.warning(f"[S20] parziale fallito #{ticket}: {r1.comment if r1 else 'err'}")
            continue
        mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": SYMBOL, "position": ticket,
                        "sl": round(st['entry'], 2), "tp": p.tp})
        st['be_done'] = True
        _s20_save_state()
        log.info(f"[S20] ✓ parziale {vol} lot @ TP1 (1R) + SL→BE  #{ticket}")

def s20_check_entry(news_paused, auto_ok, weekly_dd_pct=0.0, news_risk_mult=1.0,
                     sl_cooldowns_until=None, sl_cooldown_until=None):
    """Ogni barra M5 chiusa: se il segnale S20 è valido e non c'è già una posizione S20 aperta → apre.
    Integrata nel flusso normale: sizing via RiskGuardian (composite/tier/compounding, con lotto
    finale ×S20_LOT_MULT — unica eccezione), cooldown SL condivisi, MAX_OPEN_ORDERS e guardia
    di correlazione direzionale come le altre strategie."""
    global _s20_last_bar, _s20_last_entry_ts
    if not S20_ENABLED or not auto_ok:
        return
    candles_m5 = get_candles_tf('M5', 600)
    if not candles_m5 or len(candles_m5) < 260:
        return
    bar_t = candles_m5[-2]['t']
    if bar_t == _s20_last_bar:
        return
    _s20_last_bar = bar_t
    if _s20_state or news_paused:                        # max 1 posizione S20 / news pause
        return
    if time.time() - _s20_last_entry_ts < S20_COOLDOWN_MIN * 60:   # cooldown tra ingressi
        return
    now_utc_dt = datetime.datetime.now(datetime.timezone.utc)
    _sl_cds = sl_cooldowns_until or {}
    if _sl_cds.get(S20_TAG) and now_utc_dt < _sl_cds[S20_TAG]:
        return
    if sl_cooldown_until and now_utc_dt < sl_cooldown_until:
        return
    if count_open_positions() >= MAX_OPEN_ORDERS:
        return
    bar_dt = datetime.datetime.fromtimestamp(bar_t, tz=datetime.timezone.utc)
    I_m5 = compute_indicators(candles_m5)
    idx = len(candles_m5) - 2
    direction = signal_fib_confluence(I_m5, idx, hour=bar_dt.hour, weekday=bar_dt.weekday())
    if not direction:
        return
    if has_position_in_direction(direction):
        return
    lvl = fib_confluence_trade_levels(I_m5, idx, direction)
    if lvl is None:
        return
    risk = lvl['risk']
    tp_usd = round(risk * 2.0, 2)
    sl_usd = round(risk, 2)

    lot_use = S20_LOT
    rp = None
    rg = get_risk_guardian()
    if rg:
        acc_now = get_account_info()
        rp = rg.get_order_params(
            strategy_confidence=S20_CONFIDENCE,
            atr=risk,
            strategy_id=S20_TAG,
            ai_score=S20_AI_SCORE_PROXY,
            atr_avg=I_m5['atr_avg'][idx],
            adx=I_m5['adx'][idx],
            hour_utc=bar_dt.hour,
            today_pnl=state.pnl_today,
            current_equity=acc_now['equity'] if acc_now else None,
            weekly_dd_pct=weekly_dd_pct,
            direction=direction,
        )
        if rp.get('paused'):
            log.info(f"⛔ SEGNALE S20 SOSPESO (Risk Guardian) — comp={rp.get('composite_score')}")
            return
        lot_use = round(rp['lot'] * S20_LOT_MULT, 2)   # unica eccezione RiskGuardian per S20

    if news_risk_mult < 1.0:
        lot_use = max(0.01, round(lot_use * news_risk_mult, 2))
        log.info(f"[NewsGuardian] Lot S20 ridotto ×{news_risk_mult:.0%}")

    log.info(f"★ SEGNALE S20 (M5): {direction.upper()} | Fib Confluence | 1R=${risk:.2f} | "
             f"TP2=${tp_usd:.2f} SL=${sl_usd:.2f} | lot={lot_use}" +
             (f" | tier={rp.get('tier_label')} comp={rp.get('composite_score')}" if rp else ""))
    result = place_order(direction, tp_usd, sl_usd, S20_TAG, lot_size=lot_use)
    if not result:
        return
    ticket = getattr(result, 'order', 0)
    _strategy_order_tickets[S20_TAG] = (ticket, direction)
    state.record_trade(0, now_utc_dt)
    tick = mt5.symbol_info_tick(SYMBOL)
    entry = (tick.ask if direction == 'buy' else tick.bid) if tick else I_m5['C'][idx]
    tp1 = entry + risk if direction == 'buy' else entry - risk
    tp2 = entry + 2 * risk if direction == 'buy' else entry - 2 * risk
    _s20_state[ticket] = {'dir': direction, 'entry': round(entry, 2), 'risk': round(risk, 2),
                          'tp1': round(tp1, 2), 'tp2': round(tp2, 2), 'be_done': False}
    _s20_last_entry_ts = time.time()
    _s20_save_state()

# ── S30_DOW_DIP — US30 mean-reversion, blocco isolato (2° simbolo) ───────────
def _us30_resolve_symbol():
    """Trova il simbolo US30 attivo sul broker (una volta, a startup)."""
    global US30_SYMBOL
    for s in US30_SYMBOL_CANDIDATES:
        info = mt5.symbol_info(s)
        if info is None:
            continue
        if not info.visible:
            mt5.symbol_select(s, True)
            info = mt5.symbol_info(s)
        if info and info.visible:
            US30_SYMBOL = s
            return s
    return None

def _us30_candles_h4(n=450):
    if not US30_SYMBOL:
        return None
    rates = mt5.copy_rates_from_pos(US30_SYMBOL, mt5.TIMEFRAME_H4, 0, n)
    if rates is None or len(rates) == 0:
        log.warning(f"[S30] nessuna candela H4 {US30_SYMBOL} — {mt5.last_error()}")
        return None
    return _rates_to_list(rates)

def _us30_open_positions():
    return [p for p in (mt5.positions_get(symbol=US30_SYMBOL) or []) if p.magic == MAGIC]

def _us30_load_state():
    global _us30_state
    try:
        if os.path.exists(US30_STATE_FILE):
            with open(US30_STATE_FILE, encoding='utf-8') as f:
                _us30_state = {int(k): v for k, v in json.load(f).items()}
    except Exception as e:
        log.warning(f"[S30] load state: {e}")

def _us30_save_state():
    try:
        with open(US30_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump({str(k): v for k, v in _us30_state.items()}, f, indent=2)
    except Exception as e:
        log.warning(f"[S30] save state: {e}")

def _us30_rebuild_from_open():
    """Al riavvio: riadotta posizioni S30 aperte non ancora tracciate."""
    for p in _us30_open_positions():
        if p.ticket in _us30_state or 'S30' not in (p.comment or ''):
            continue
        _us30_state[p.ticket] = {'entry': p.price_open, 'sl': p.sl, 'tp': p.tp, 'open_ts': p.time}
        log.info(f"[S30] posizione riadottata al riavvio: #{p.ticket} @ {p.price_open}")
    if _us30_state:
        _us30_save_state()

def _us30_close_position(p, reason):
    if DRY_RUN:
        log.info(f"[S30][DRY] chiusura #{p.ticket} ({reason})")
        _us30_state.pop(p.ticket, None); _us30_save_state()
        return
    tick = mt5.symbol_info_tick(US30_SYMBOL)
    if not tick:
        return
    close_type = mt5.ORDER_TYPE_SELL if p.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    px = tick.bid if p.type == mt5.ORDER_TYPE_BUY else tick.ask
    r = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": US30_SYMBOL, "position": p.ticket,
                        "volume": p.volume, "type": close_type, "price": px, "deviation": 30,
                        "magic": MAGIC, "comment": "TF-AI S30 exit",
                        "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC})
    if r and r.retcode == mt5.TRADE_RETCODE_DONE:
        log.info(f"[S30] ✓ chiusura #{p.ticket} ({reason})")
        _us30_state.pop(p.ticket, None); _us30_save_state()
    else:
        log.warning(f"[S30] chiusura fallita #{p.ticket}: {r.comment if r else 'err'}")

def _us30_manage():
    """Rileva posizioni chiuse (pulisce lo stato) + time-stop."""
    if not US30_ENABLED or not _us30_state:
        return
    open_pos = {p.ticket: p for p in _us30_open_positions()}
    for ticket in list(_us30_state):
        st = _us30_state[ticket]
        if ticket not in open_pos:
            _us30_state.pop(ticket, None); _us30_save_state()
            log.info(f"[S30] posizione #{ticket} chiusa (TP/SL)")
            continue
        held_h = (time.time() - st.get('open_ts', time.time())) / 3600
        if held_h > US30_MAX_BARS * 4:
            _us30_close_position(open_pos[ticket], f"time-stop {held_h:.0f}h")

def _us30_place_order(sl_pts, tp_pts, lot):
    tick = mt5.symbol_info_tick(US30_SYMBOL)
    info = mt5.symbol_info(US30_SYMBOL)
    if not tick or not info:
        log.error("[S30] tick/info simbolo non disponibili")
        return None
    digits = info.digits
    price = tick.ask
    sl_price = round(price - sl_pts, digits)
    tp_price = round(price + tp_pts, digits)
    min_stop = (getattr(info, 'trade_stops_level', 0) or 0) * info.point
    if min_stop:
        if price - sl_price < min_stop:
            sl_price = round(price - min_stop * 1.5, digits)
        if tp_price - price < min_stop:
            tp_price = round(price + min_stop * 1.5, digits)
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": US30_SYMBOL, "volume": lot,
           "type": mt5.ORDER_TYPE_BUY, "price": price, "sl": sl_price, "tp": tp_price,
           "deviation": 30, "magic": MAGIC, "comment": f"TF-AI {US30_TAG}",
           "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC}
    if DRY_RUN:
        import random
        t = random.randint(100000, 999999)
        log.info(f"[DRY-RUN] Ordine simulato: BUY {lot} {US30_SYMBOL} @ {price:.2f}  "
                 f"TP={tp_price:.2f}  SL={sl_price:.2f}  [{US30_TAG}] ticket={t}")
        class _DryResult:
            retcode = 10009; order = t; simulated = True
        return _DryResult(), price, sl_price, tp_price
    r = mt5.order_send(req)
    if not r or r.retcode != mt5.TRADE_RETCODE_DONE:
        log.error(f"[S30] ordine fallito: retcode={r.retcode if r else '?'} — {r.comment if r else ''}")
        return None
    log.info(f"[S30] ✓ ordine #{r.order} BUY {lot} {US30_SYMBOL} @ {price:.2f}  "
             f"TP={tp_price:.2f}  SL={sl_price:.2f}")
    return r, price, sl_price, tp_price

def _us30_check_entry(news_paused, auto_ok):
    """Ogni barra H4 chiusa: segnale S30_DOW_DIP valido + nessuna posizione S30 aperta → apre."""
    global _us30_last_bar, _us30_last_entry_ts
    if not US30_ENABLED or not auto_ok or not US30_SYMBOL:
        return
    candles = _us30_candles_h4(450)
    if not candles or len(candles) < 300:
        return
    bar_t = candles[-2]['t']
    if bar_t == _us30_last_bar:
        return
    _us30_last_bar = bar_t
    if _us30_state or news_paused:                                   # max 1 posizione S30
        return
    if time.time() - _us30_last_entry_ts < US30_COOLDOWN_H * 3600:
        return
    if is_hard_blocked(US30_TAG):                                    # safety net self-learning
        return
    I = compute_indicators(candles)
    idx = len(candles) - 2
    if signal_dow_dip(I, idx) != 'buy':
        return
    av = I['atr'][idx]
    if not av:
        return
    sl_pts = round(av * US30_SL_ATR, 2)
    tp_pts = round(av * US30_TP_ATR, 2)
    log.info(f"★ SEGNALE S30_DOW_DIP (H4): BUY {US30_SYMBOL} | RSI(2) oversold in uptrend | "
             f"ATR={av:.1f}  TP={tp_pts:.0f}pt  SL={sl_pts:.0f}pt  lot={US30_LOT}")
    res = _us30_place_order(sl_pts, tp_pts, US30_LOT)
    if not res:
        return
    result, entry, sl_price, tp_price = res
    ticket = getattr(result, 'order', 0)
    _us30_state[ticket] = {'entry': round(entry, 2), 'sl': round(sl_price, 2),
                           'tp': round(tp_price, 2), 'open_ts': time.time()}
    _us30_save_state()
    _us30_last_entry_ts = time.time()

# ── VERCEL SYNC ───────────────────────────────────────────────────────────────
def get_open_positions_data():
    """Legge le posizioni aperte da MT5 e le serializza"""
    pos = mt5.positions_get(symbol=SYMBOL)
    if not pos: return []
    result = []
    for p in pos:
        if p.magic != MAGIC: continue
        net_p = round((p.profit or 0) + (p.swap or 0), 2)
        result.append({
            'ticket':      p.ticket,
            'position_id': p.identifier,
            'direction':   'buy' if p.type == 0 else 'sell',
            'lot':         p.volume,
            'entry':       round(p.price_open, 2),
            'current':     round(p.price_current, 2),
            'tp':          round(p.tp, 2),
            'sl':          round(p.sl, 2),
            'profit':      net_p,
            'strategy':    p.comment.replace('TF-AI ', '') if p.comment else 'N/A',
            'time':        datetime.datetime.fromtimestamp(p.time, tz=datetime.timezone.utc).isoformat(),
        })
    return result

def get_recent_trades_data(n=200, retries=3, retry_delay=2.0):
    """
    Legge gli ultimi N trade chiusi da MT5, raggruppati per position_id.

    Raggruppa ENTRY + EXIT deal per position_id in modo da leggere il nome
    della strategia dall'ENTRY deal (unico con commento "TF-AI Sxx_...").
    EXIT deal ha commento "tp"/"sl"/"" → usato solo per profit/close_reason.

    Mostra TUTTI i trade chiusi dell'account (inclusi manuali) — il filtro
    magic è applicato solo nel PerformanceTracker per il self-learning.
    Retry con delay per gestire la race condition MT5: il deal appare in
    history_deals_get 1-5s dopo che la posizione sparisce da positions_get.
    """
    utc = datetime.timezone.utc
    for attempt in range(retries):
        try:
            now_ts  = int(time.time())
            from_ts = now_ts - 365 * 86400   # ultimi 12 mesi
            to_ts   = now_ts + 3600

            deals = mt5.history_deals_get(from_ts, to_ts)

            if deals is None:
                err = mt5.last_error()
                log.warning(f"📋 history_deals_get → None (attempt {attempt+1}/{retries}) | MT5 error: {err}")
                if attempt < retries - 1:
                    time.sleep(retry_delay)
                continue

            total_raw = len(deals)

            # Raggruppa per position_id: entry (entry==0) + exit(s) (entry==1/2/3)
            by_pos = {}
            for d in deals:
                if d.type not in (0, 1):  # solo BUY/SELL deal
                    continue
                pid = d.position_id
                if pid not in by_pos:
                    by_pos[pid] = {'entry': None, 'exits': []}
                if d.entry == 0:
                    by_pos[pid]['entry'] = d
                else:
                    by_pos[pid]['exits'].append(d)

            # Costruisci trade chiusi (quelli con sia entry che exit)
            closed_trades = []
            for pid, pos_deals in by_pos.items():
                entry_d = pos_deals['entry']
                exits   = pos_deals['exits']
                if not entry_d or not exits:
                    continue  # posizione ancora aperta o deal incompleto

                last_exit  = max(exits, key=lambda d: d.time)
                net_profit = round(sum(
                    (d.profit or 0) + (d.commission or 0) + (d.swap or 0)
                    for d in exits
                ), 2)
                raw_comment = entry_d.comment or ''
                if 'TF-AI' in raw_comment:
                    strategy = raw_comment.replace('TF-AI ', '').strip()
                else:
                    strategy = raw_comment.strip() or 'manual'

                closed_trades.append({
                    'position_id': pid,
                    'ticket':      entry_d.ticket,
                    'time':        datetime.datetime.fromtimestamp(last_exit.time, tz=utc).isoformat(),
                    'time_open':   datetime.datetime.fromtimestamp(entry_d.time, tz=utc).isoformat(),
                    'direction':   'buy' if entry_d.type == 0 else 'sell',
                    'strategy':    strategy,
                    'entry_price': round(entry_d.price, 2),
                    'price':       round(last_exit.price, 2),
                    'volume':      entry_d.volume,
                    'profit':      net_profit,
                    'profit_raw':  round(sum(d.profit or 0 for d in exits), 2),
                    'commission':  round(sum(d.commission or 0 for d in exits), 2),
                    'swap':        round(sum(d.swap or 0 for d in exits), 2),
                    'close_reason': last_exit.comment or '',
                })

            closed_trades.sort(key=lambda t: t['time'], reverse=True)
            result = closed_trades[:n]
            log.info(f"📋 MT5 history: {total_raw} deal raw → {len(by_pos)} posizioni → {len(result)} chiuse mostrate")
            return result

        except Exception as e:
            log.warning(f"MT5 history_deals errore (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(retry_delay)

    # Fallback su file locale solo se MT5 ha dato eccezione tutti i tentativi
    log.warning("📋 Fallback su mt5-trades.json (MT5 non disponibile)")
    fname = 'mt5-trades.json'
    if not os.path.exists(fname):
        return []
    with open(fname, encoding='utf-8') as f:
        try:
            trades = json.load(f)
        except Exception:
            return []
    return trades[-n:]

def s20_push_stats(trades):
    """Aggrega i trade S20 reali (da get_recent_trades_data) e li POSTa per la card nel tab Strategie."""
    if not SYNC_ENABLED or not VERCEL_URL:
        return
    s20 = [t for t in (trades or []) if str(t.get('strategy', '')).startswith('S20')]
    def agg(rows):
        if not rows:
            return None
        n = len(rows); wins = [r for r in rows if r['profit'] > 0]
        gw = sum(r['profit'] for r in wins)
        gl = abs(sum(r['profit'] for r in rows if r['profit'] <= 0)) or 1e-9
        return {'n': n, 'wr': round(100 * len(wins) / n, 1), 'pf': round(gw / gl, 3),
                'pnl': round(sum(r['profit'] for r in rows), 2)}
    cum = 0.0; eq = []
    for r in sorted(s20, key=lambda x: x['time']):
        cum += r['profit']; eq.append({'t': r['time'][:10], 'cum': round(cum, 2)})
    summary = {
        'mode': 'live', 'lot': f'RiskGuardian ×{S20_LOT_MULT}',
        'config': 'v2 · M5 · SL strutturale · TP1 1R (parz.) / TP2 2R · London+NY · no-lunedì · integrata',
        'n_total': len(s20), 'n_open': len(_s20_state),
        'overall': agg(s20),
        'buy':  agg([r for r in s20 if r['direction'] == 'buy']),
        'sell': agg([r for r in s20 if r['direction'] == 'sell']),
        'equity': eq[-60:],
        'recent': [{'bar_utc': r['time'], 'dir': r['direction'],
                    'resolution': r.get('close_reason', ''), 'pnl': r['profit']}
                   for r in sorted(s20, key=lambda x: x['time'])[-8:]],
    }
    try:
        req = urllib.request.Request(
            f"{VERCEL_URL}/api/db",
            data=json.dumps({'action': 's20_paper_push', 'secret': MT5_SECRET, 'summary': summary}).encode(),
            headers={'Content-Type': 'application/json'}, method='POST')
        urllib.request.urlopen(req, timeout=8, context=_SSL_CTX).read()
    except Exception as e:
        log.debug(f"[S20] push stats: {e}")

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

    # ── Imposta auto_trade = True al boot ────────────────────────────────────
    # Il bot trada autonomamente di default — l'utente può disabilitare dalla UI mentre è in running.
    if SYNC_ENABLED and VERCEL_URL:
        try:
            _at_boot = urllib.request.Request(
                f"{VERCEL_URL}/api/db",
                data=json.dumps({'action': 'auto_trade_set', 'enabled': True}).encode(),
                headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(_at_boot, timeout=6, context=_SSL_CTX) as _r:
                _d = json.loads(_r.read())
                if _d.get('ok'):
                    log.info("🤖 Auto-trading ATTIVATO (set al boot su DB Vercel)")
        except Exception as _e:
            log.warning(f"Auto-trade boot-set fallito ({_e}) — uso default True locale")

    load_playbook()

    acc = get_account_info()
    if acc:
        log.info(f"Account: {acc['balance']:.2f} {acc['currency']} "
                 f"(equity={acc['equity']:.2f}, free margin={acc['margin_free']:.2f})")

    last_bar_time      = None   # per rilevare nuova candela H1
    last_bar_time_m15  = None   # per rilevare nuova candela M15
    last_bar_time_m30  = None   # per rilevare nuova candela M30
    last_bar_time_h4   = None   # per rilevare nuova candela H4 (S17_CONVERGENCE_SCALP)
    current_regime     = 'UNKNOWN'
    current_is_extreme = False
    last_sync_time       = -999  # forza sync immediato al primo ciclo
    last_ai_score        = 50.0  # default neutro
    last_score_ts        = 0     # timestamp ultimo fetch score
    last_cmd_ts          = 0     # timestamp ultimo check comandi manuali
    auto_trade_enabled   = True  # letto da DB Vercel: se False, loop H1/M30/H4 non aprono ordini
    last_auto_trade_ts   = 0     # timestamp ultimo fetch flag auto_trade
    reconnect_attempts   = 0     # contatore per exponential backoff MT5
    last_candle_fetch_ts = 0     # timestamp ultimo fetch candele H1
    cached_candles       = None  # cache candele (aggiornata ogni 60s)
    cached_I_h1          = None  # cache indicatori (ricalcolati solo su nuova barra)
    _tracked_positions   = {}    # {ticket: position_id} per rilevare chiusure istantanee
    consecutive_sl_count    = 0    # SL consecutivi globali: azzerato a ogni TP/profit
    _last_logged_ai_score   = None  # dedup entries in ai_score_history.json
    sl_cooldown_until    = None  # datetime UTC fino a cui nuovi ordini sono bloccati globale
    _strategy_sl_count   = {}    # {strategy_name: consecutive_sl_count}
    sl_cooldowns_until   = {}    # {strategy_name: datetime UTC} pausa specifica per strategia
    _stale_strikes       = set() # {strategy_name} entry stale al sync precedente (fix deadlock 2026-09-02)
    weekly_dd_pct        = 0.0   # drawdown settimanale reale (aggiornato ogni sync)
    _live_dedup          = set() # dedup live scan: {(strat, dir, tf, bar_open_t)}
    _m30_live_cache      = None  # indicatori M30 per live scan (aggiornati ogni 60s)
    _m30_live_cnds       = None  # candles M30 per live scan
    _m30_live_ts         = 0.0   # timestamp ultimo refresh M30 live

    # Inizializza RiskManager (legacy, mantiene compatibilità)
    rm = get_risk_manager(base_lot=LOT_SIZE, max_lot=LOT_SIZE*5) if get_risk_manager else None
    if rm:
        log.info(f"RiskManager attivo — base_lot={LOT_SIZE} max_lot={LOT_SIZE*5}")
    else:
        log.warning("RiskManager disabilitato — uso lot size fisso")

    # Inizializza Risk Guardian (obbligatorio)
    acc_init = get_account_info()
    initial_equity = acc_init['equity'] if acc_init else 10000.0
    rg = get_risk_guardian(base_lot=LOT_SIZE, max_lot=LOT_SIZE*5,
                           initial_equity=initial_equity)
    log.info(f"RiskGuardian attivo — equity iniziale={initial_equity:.2f}")

    # Sincronizza _strategy_order_tickets da posizioni MT5 già aperte (riavvio bot)
    _existing = mt5.positions_get(symbol=SYMBOL) or []
    for _p in _existing:
        if _p.magic == MAGIC and _p.comment and _p.comment.startswith('TF-AI '):
            _strat = _p.comment.replace('TF-AI ', '').strip()
            _pdir = 'buy' if _p.type == mt5.ORDER_TYPE_BUY else 'sell'
            _strategy_order_tickets[_strat] = (_p.ticket, _pdir)
    if _strategy_order_tickets:
        log.info(f"Posizioni rilevate al riavvio: {list(_strategy_order_tickets.keys())}")

    # S20_FIB_CONFLUENCE (integrata nel flusso normale): ripristina stato + riadotta posizioni aperte
    if S20_ENABLED:
        _s20_load_state()
        s20_rebuild_from_open()
        log.info(f"S20_FIB_CONFLUENCE attiva — M5 · sizing RiskGuardian ×{S20_LOT_MULT} · "
                 f"cooldown SL condivisi · {len(_s20_state)} posizioni in gestione")

    # S30_DOW_DIP — blocco isolato su 2° simbolo (US30)
    us30_ok = False
    if US30_ENABLED:
        _sym = _us30_resolve_symbol()
        if _sym:
            _us30_load_state()
            _us30_rebuild_from_open()
            us30_ok = True
            log.info(f"S30_DOW_DIP attiva — {_sym} H4 · mean-reversion long-only · lot {US30_LOT} fisso · "
                     f"isolata (2° simbolo, no selector/RG/compounding) · {len(_us30_state)} posizioni")
        else:
            log.warning("S30_DOW_DIP: simbolo US30 non trovato sul broker — disattivata per questa sessione")

    # Inizializza Strategy Selector Agent
    strategy_selector = StrategySelector() if StrategySelector else None
    if strategy_selector:
        log.info("StrategySelector attivo — selezione dinamica regime-based")
    else:
        log.info("StrategySelector non disponibile — uso playbook statico")

    # Stato agente selettore (aggiornato ogni barra M30/H1)
    current_selector_result = None
    last_selector_bar_time  = None

    # Inizializza Key Levels Agent
    kla = get_key_levels_agent() if get_key_levels_agent else None
    current_levels_result = None  # aggiornato ogni barra H1
    # Cache per TF higher (D1 aggiornato ogni 24h, H4 ogni 4h)
    cached_I_d1  = None;  cached_candles_d1  = None;  last_d1_bar_time  = None
    cached_I_h4  = None;  cached_candles_h4  = None;  last_h4_bar_time  = None
    if kla:
        log.info("KeyLevelsAgent attivo — multi-TF (D1 1.0 / H4 0.9 / H1 0.7)")

    # Inizializza Performance Tracker (self-learning)
    perf_tracker     = get_performance_tracker(MAGIC) if get_performance_tracker else None
    last_perf_report = 0  # timestamp ultimo report 6h
    if perf_tracker:
        log.info("PerformanceTracker attivo — self-learning abilitato")

    # Inizializza News Guardian
    news_guardian      = get_news_guardian() if get_news_guardian else None
    current_news_risk  = {'paused': False, 'risk_mult': 1.0, 'reason': 'clear'}
    last_news_check_ts = 0  # refresh ogni 15min
    if news_guardian:
        news_guardian.refresh(force=True)
        upcoming = news_guardian.get_upcoming_high_impact(hours_ahead=12)
        if upcoming:
            log.info(f"[NewsGuardian] {len(upcoming)} news HIGH USD/XAU prossime 12h:")
            for e in upcoming[:3]:
                log.info(f"  • {e['dt'][11:16]} UTC (+{e['minutes_away']}min) {e['currency']} {e['title']}")
        log.info("NewsGuardian attivo — pausa automatica attorno a news USD/XAU HIGH impact")

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
                    cached_I_h1 = compute_indicators(cached_candles)  # aggiorna indicatori live ogni 60s
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
                # Rileva posizioni chiuse tra un sync e l'altro via position_id reale
                cur_pos_ids = {p['ticket']: p for p in positions_data}
                closed_this_cycle = []
                for ticket, pos_id in list(_tracked_positions.items()):
                    if ticket not in cur_pos_ids:
                        # position_id MT5 reale (p.identifier) salvato all'apertura
                        extra = mt5.history_deals_get(position=pos_id)
                        net_profit = 0.0
                        strategy_closed = 'N/A'
                        if extra:
                            for d in extra:
                                if d.type in (0, 1) and d.entry != 0:
                                    net_profit += (d.profit or 0) + (d.commission or 0) + (d.swap or 0)
                                    if d.comment and d.comment.startswith('TF-AI '):
                                        strategy_closed = d.comment.replace('TF-AI ', '')
                            # Il broker tronca il comment MT5 a ~16 char (es. 'S18_RANGE_' invece
                            # di 'S18_RANGE_REVERSAL') → risolvi il nome pieno per ticket match
                            # contro _strategy_order_tickets invece di fidarsi del comment troncato,
                            # altrimenti il pop sotto fallisce silenziosamente e la entry resta
                            # bloccata per sempre in count_open_positions() (vedi 06_known_issues.md)
                            for _sname, (_tkt, _dir) in _strategy_order_tickets.items():
                                if _tkt == ticket:
                                    strategy_closed = _sname
                                    break
                        if extra:
                            log.info(
                                f"🎯 Chiusura rilevata: ticket#{ticket} pos_id={pos_id} "
                                f"| {strategy_closed} | net_profit={net_profit:+.2f}"
                            )
                            closed_this_cycle.append(ticket)
                            # Aggiorna contatore SL consecutivi globale e per strategia
                            # (S20_FIB_CONFLUENCE integrata 2026-09-01: partecipa ai cooldown come le altre)
                            if net_profit < 0:
                                consecutive_sl_count += 1
                                if strategy_closed != 'N/A':
                                    s_id = strategy_closed
                                    _strategy_sl_count[s_id] = _strategy_sl_count.get(s_id, 0) + 1
                                    if _strategy_sl_count[s_id] >= 2:
                                        sl_cooldowns_until[s_id] = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=STRATEGY_SL_COOLDOWN_H)
                                        log.warning(f"🛑 COOLDOWN ATTIVO ({s_id}): {_strategy_sl_count[s_id]} SL consecutivi → pausa {STRATEGY_SL_COOLDOWN_H}h (fino a {sl_cooldowns_until[s_id].strftime('%H:%M')} UTC)")

                                if consecutive_sl_count >= 2:
                                    sl_cooldown_until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=SL_COOLDOWN_H)
                                    log.warning(
                                        f"🛑 COOLDOWN GLOBALE ATTIVO: {consecutive_sl_count} SL consecutivi "
                                        f"→ pausa fino a {sl_cooldown_until.strftime('%H:%M')} UTC"
                                    )
                            else:
                                consecutive_sl_count = 0  # profit → reset streak globale
                                if strategy_closed != 'N/A':
                                    _strategy_sl_count[strategy_closed] = 0 # reset streak strategia
                                    
                            # Rimuovi dalla tracking in-memory
                            if strategy_closed != 'N/A':
                                _strategy_order_tickets.pop(strategy_closed, None)
                        _tracked_positions.pop(ticket, None)
                # Aggiorna tracking posizioni correnti (usa identifier MT5 come pos_id)
                for ticket, p in cur_pos_ids.items():
                    if ticket not in _tracked_positions:
                        # position_id è p['position_id'] = pos.identifier in MT5
                        _tracked_positions[ticket] = p.get('position_id') or ticket

                # ── Riconciliazione _strategy_order_tickets vs MT5 (fix deadlock 2026-09-02) ──
                # count_open_positions() = max(mt5_count, len(_strategy_order_tickets)): una entry
                # stale (pop fallito perché strategy_closed='N/A', o comment troncato non risolto)
                # gonfia il conteggio per SEMPRE → tutti i blocchi segnale vedono
                # count_open_positions() >= MAX_OPEN_ORDERS PRIMA del self-heal in
                # has_open_position_for_strategy() → deadlock permanente (bot fermo dal 2026-07-10).
                # Fonte di verità = MT5. Due-strike: rimuovi solo dopo 2 sync consecutivi stale,
                # così una posizione appena aperta ancora non visibile in MT5 (latenza ~500ms)
                # non viene tolta per errore.
                if not DRY_RUN and (positions_data or mt5.positions_get(symbol=SYMBOL) is not None):
                    _live_tickets = set(cur_pos_ids)
                    _now_stale = {s for s, (tk, _d) in _strategy_order_tickets.items()
                                  if tk and tk not in _live_tickets}
                    for s in (_now_stale & _stale_strikes):     # stale su 2 sync consecutivi
                        log.info(f"🧹 Riconciliazione: rimuovo entry stale {s} (ticket assente da MT5 per 2 sync)")
                        _strategy_order_tickets.pop(s, None)
                        _strategy_sl_count.pop(s, None)
                    _stale_strikes = {s for s in _now_stale if s in _strategy_order_tickets}

                # Se ci sono chiusure rilevate: attendi 3s (race condition MT5),
                # poi forza sync immediato così il deal è già in history
                if closed_this_cycle:
                    time.sleep(3)
                    last_sync_time = 0  # forza anche il prossimo sync a breve

                trades_data = get_recent_trades_data(200)
                today_str = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
                log.info(f"📊 Sync: {len(trades_data)} trade totali, {sum(1 for t in trades_data if t['time'][:10]==today_str)} oggi | last: {trades_data[0]['time'][:16] if trades_data else 'nessuno'}")
                pnl_today_real = round(sum(t['profit'] for t in trades_data if t['time'][:10] == today_str), 2)
                trades_today_real = sum(1 for t in trades_data if t['time'][:10] == today_str)
                # ── Weekly drawdown reale: somma profitti ultimi 7gg vs equity corrente ─
                try:
                    _week_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)).date().isoformat()
                    _weekly_pnl = sum(t['profit'] for t in trades_data if t.get('time','')[:10] >= _week_ago)
                    _cur_equity = acc_data['equity'] if acc_data and acc_data.get('equity') else initial_equity
                    if _cur_equity > 0 and _weekly_pnl < 0:
                        weekly_dd_pct = round(abs(_weekly_pnl) / _cur_equity, 4)
                    else:
                        weekly_dd_pct = 0.0
                except Exception:
                    weekly_dd_pct = 0.0
                _sl_cd_ts = sl_cooldown_until.isoformat() if sl_cooldown_until else None
                _rg_last = rg._last_params if rg and getattr(rg, '_last_params', None) else None
                bot_status = {
                    'running': True,
                    'dry_run': DRY_RUN,
                    'symbol': SYMBOL,
                    'lot': LOT_SIZE,
                    'trades_today': trades_today_real,
                    'pnl_today': pnl_today_real,
                    'regime': current_regime,
                    'last_bar': datetime.datetime.fromtimestamp(last_bar_time, tz=datetime.timezone.utc).isoformat() if last_bar_time else None,
                    'active_strategy': current_selector_result['selected_strategy'] if current_selector_result else None,
                    'strategy_confidence': current_selector_result['confidence'] if current_selector_result else None,
                    'selector_reasoning': current_selector_result['reasoning'] if current_selector_result else None,
                    'open_positions': count_open_positions(),
                    'consecutive_sl': consecutive_sl_count,
                    'sl_cooldown_until': _sl_cd_ts,
                    'news_paused':    current_news_risk.get('paused', False),
                    'news_reason':    current_news_risk.get('reason', ''),
                    'news_risk_mult': current_news_risk.get('risk_mult', 1.0),
                    'rg_tier':        _rg_last.get('tier_label', '—') if _rg_last else '—',
                    'rg_composite':   _rg_last.get('composite_score') if _rg_last else None,
                    'rg_lot':         _rg_last.get('lot') if _rg_last else None,
                    'last_logs':      _ring_handler.get_lines(),
                }
                sync_to_vercel(acc_data, positions_data, trades_data, bot_status)
                if S20_ENABLED:
                    s20_push_stats(trades_data)
                last_sync_time = now_ts

            # ── News Guardian: aggiorna rischio ogni 60s (era 15min — bug timezone fix 2026-04-28) ──
            if news_guardian and (now_ts - last_news_check_ts) >= 60:
                last_news_check_ts = now_ts
                new_risk = news_guardian.check_news_risk(now_utc)
                # Log solo se cambia stato
                if new_risk['paused'] != current_news_risk['paused'] or \
                   new_risk['risk_mult'] != current_news_risk['risk_mult']:
                    if new_risk['paused']:
                        log.warning(f"[NewsGuardian] {new_risk['reason']}")
                    elif new_risk['risk_mult'] < 1.0:
                        log.info(f"[NewsGuardian] {new_risk['reason']}")
                    elif current_news_risk['paused'] or current_news_risk['risk_mult'] < 1.0:
                        log.info("[NewsGuardian] ✅ Finestra news terminata — trading ripreso")
                current_news_risk = new_risk

            # ── Performance Tracker: report ogni 6 ore ─────────────────────
            if perf_tracker and (now_ts - last_perf_report) >= 21600:
                log.info(perf_tracker.get_performance_report())
                last_perf_report = now_ts

            # ── Fetch AI Score ogni 60s ────────────────────────────────────
            if (now_ts - last_score_ts) >= 60:
                global current_ai_score
                _fetched_score = None
                # Guard: RiskManager potrebbe non essere importato (BUG#2 fix 2026-04-23)
                if RiskManager is not None:
                    _fetched_score = RiskManager.fetch_ai_score(VERCEL_URL)  # None se offline
                else:
                    try:
                        # Fallback: fetch diretto senza RiskManager
                        import urllib.request as _ur, json as _json
                        _req = _ur.Request(f"{VERCEL_URL}/api/db",
                            data=_json.dumps({'action':'mt5_get','secret':MT5_SECRET}).encode(),
                            headers={'Content-Type':'application/json'}, method='POST')
                        with _ur.urlopen(_req, timeout=8, context=_SSL_CTX) as _r:
                            _d = _json.loads(_r.read())
                            _v = (_d.get('bot_status') or {}).get('ai_score')
                            if _v is not None:
                                _fetched_score = float(_v)
                    except Exception:
                        pass

                if _fetched_score is not None:
                    # Applica sempre la SL-streak penalty anche quando Vercel è online:
                    # se abbiamo SL consecutivi, limitiamo lo score al massimo locale
                    # (Vercel può restare stale a 50.0 per ore senza riflettere le perdite)
                    _local_penalty = _local_ai_score(consecutive_sl_count, state.pnl_today)
                    if consecutive_sl_count > 0:
                        current_ai_score = min(_fetched_score, _local_penalty)
                        _score_source = f"Vercel+SL({consecutive_sl_count})"
                    else:
                        current_ai_score = _fetched_score
                        _score_source = "Vercel"
                else:
                    # Vercel offline: calcola proxy locale da streak SL + pnl giornaliero
                    current_ai_score = _local_ai_score(consecutive_sl_count, state.pnl_today)
                    _score_source = f"locale (SL streak={consecutive_sl_count})"

                last_ai_score = current_ai_score
                last_score_ts = now_ts
                if rm:
                    log.info(f"🧠 AI Score: {last_ai_score:.1f} [{_score_source}] — tier: {rm.get_tier(last_ai_score)['label']}")
                else:
                    log.info(f"🧠 AI Score: {last_ai_score:.1f} [{_score_source}]")
                # Salva in history solo quando lo score cambia (evita flood di entries identiche)
                if _last_logged_ai_score is None or abs(current_ai_score - _last_logged_ai_score) >= 0.5:
                    _hs_tier = rm.get_tier(last_ai_score)['label'].split(' ', 1)[-1] if rm else (
                        'NORMAL' if last_ai_score >= 40 else 'CONSERVATIVE')
                    _hs_comp = (rg._last_params or {}).get('composite_score') if rg else None
                    _append_ai_score_history(current_ai_score, _score_source, _hs_tier, _hs_comp)
                    _last_logged_ai_score = current_ai_score

            # ── Fetch auto_trade flag ogni 30s ────────────────────────────────
            if (now_ts - last_auto_trade_ts) >= 30:
                try:
                    _at_req = urllib.request.Request(
                        f"{VERCEL_URL}/api/db",
                        data=json.dumps({'action': 'auto_trade_get'}).encode(),
                        headers={'Content-Type': 'application/json'}, method='POST')
                    with urllib.request.urlopen(_at_req, timeout=6, context=_SSL_CTX) as _at_r:
                        _at_d = json.loads(_at_r.read())
                        if _at_d.get('ok') and isinstance(_at_d.get('enabled'), bool):
                            _prev_at = auto_trade_enabled
                            auto_trade_enabled = _at_d['enabled']
                            if auto_trade_enabled != _prev_at:
                                log.info(f"🤖 Auto-trading {'ATTIVATO' if auto_trade_enabled else 'DISATTIVATO'} (da DB Vercel)")
                except Exception:
                    pass  # fallback: mantieni valore precedente (True di default)
                last_auto_trade_ts = now_ts

            # ── Controlla nuova candela H1 ────────────────────────────────────
            latest_bar_time = candles[-2]['t']   # -2 = ultima barra chiusa
            new_h1_bar = (latest_bar_time != last_bar_time)

            # Ricalcola indicatori solo su nuova barra H1 (1×/ora, non ogni 10s)
            if cached_I_h1 is None or new_h1_bar:
                cached_I_h1 = compute_indicators(candles)
            I_h1 = cached_I_h1
            i_h1 = len(candles) - 2

            atr_now = I_h1['atr'][i_h1] if I_h1['atr'][i_h1] else 10.0
            if rg:
                rg.manage_positions(mt5, SYMBOL, MAGIC, atr_now, current_regime)
            elif rm:
                rm.manage_positions(mt5, SYMBOL, MAGIC, atr_now)

            if new_h1_bar:
                last_bar_time = latest_bar_time
                bar_dt = datetime.datetime.fromtimestamp(latest_bar_time, tz=datetime.timezone.utc)
                log.info(f"─── Nuova barra H1 chiusa: {bar_dt.strftime('%Y-%m-%d %H:%M')} UTC ───")

                # ── Aggiorna Regime ───────────────────────────────────────────
                current_regime = detect_regime(I_h1, i_h1)

                # ── Performance Tracker: aggiorna storico + applica aggiustamenti ──
                recent_wr_map = {}
                if perf_tracker:
                    try:
                        perf_tracker.update_from_mt5(mt5)
                        perf_tracker.auto_apply_adjustments()
                        recent_wr_map = perf_tracker.get_recent_wr_map()
                    except Exception as e:
                        log.warning(f"[PerfTracker] update error: {e}")

                # ── Strategy Selector Agent (ogni barra H1) ───────────────────
                if strategy_selector:
                    current_selector_result = strategy_selector.select(
                        I_h1, i_h1, bar_dt.hour,
                        recent_wr_map=recent_wr_map or None
                    )
                    last_selector_bar_time = latest_bar_time

                # ── Key Levels Agent: fetch D1 / H4, merge multi-TF ──────────
                if kla:
                    try:
                        # D1: aggiorna solo se nuova candela daily
                        candles_d1_new = get_candles_tf('D1', 200)
                        if candles_d1_new:
                            d1_bar = candles_d1_new[-2]['t']
                            if d1_bar != last_d1_bar_time:
                                cached_candles_d1 = candles_d1_new
                                cached_I_d1 = compute_indicators(candles_d1_new)
                                last_d1_bar_time = d1_bar

                        # H4: aggiorna solo se nuova candela H4
                        candles_h4_new = get_candles_tf('H4', 300)
                        if candles_h4_new:
                            h4_bar = candles_h4_new[-2]['t']
                            if h4_bar != last_h4_bar_time:
                                cached_candles_h4 = candles_h4_new
                                cached_I_h4 = compute_indicators(candles_h4_new)
                                last_h4_bar_time = h4_bar

                        tf_inputs = [
                            {"tf": "H1",  "I": I_h1,        "i": i_h1,
                             "candles": candles},
                        ]
                        if cached_I_h4:
                            tf_inputs.insert(0, {
                                "tf": "H4", "I": cached_I_h4,
                                "i": len(cached_candles_h4) - 2,
                                "candles": cached_candles_h4,
                            })
                        if cached_I_d1:
                            tf_inputs.insert(0, {
                                "tf": "D1", "I": cached_I_d1,
                                "i": len(cached_candles_d1) - 2,
                                "candles": cached_candles_d1,
                            })

                        current_levels_result = kla.get_multi_tf_levels(
                            tf_inputs, atr=I_h1['atr'][i_h1]
                        )
                    except Exception as _kl_err:
                        log.debug(f"[KeyLevels] multi-tf error: {_kl_err}")
                        current_levels_result = None

                # ── Controllo giorno estremo ──────────────────────────────────
                atr_v   = I_h1['atr'][i_h1]
                atr_avg = I_h1['atr_avg'][i_h1]
                current_is_extreme = bool(atr_v and atr_avg and atr_v > EXTREME_MULT * atr_avg)

                # ── RiskGuardian preview (aggiorna tier/composite senza ordine) ─
                if rg and atr_v:
                    _prev_conf = current_selector_result['confidence'] if current_selector_result else last_ai_score / 100.0
                    _acc_prev = get_account_info()
                    rg.update_preview(
                        strategy_confidence=_prev_conf,
                        ai_score=last_ai_score,
                        atr=atr_v,
                        atr_avg=atr_avg or atr_v,
                        hour_utc=bar_dt.hour,
                        adx=I_h1['adx'][i_h1],
                        today_pnl=state.pnl_today,
                        current_equity=_acc_prev['equity'] if _acc_prev else None,
                    )
                    # Snapshot orario: score + composite + regime (una entry per candela H1)
                    _snap_comp = (rg._last_params or {}).get('composite_score')
                    _snap_tier = rm.get_tier(last_ai_score)['label'].split(' ', 1)[-1] if rm else 'UNKNOWN'
                    _append_ai_score_history(last_ai_score, 'H1_snapshot', _snap_tier,
                                             _snap_comp, current_regime)
                    _last_logged_ai_score = last_ai_score

                if current_is_extreme:
                    log.info(f"⚠ Giorno estremo (ATR={atr_v:.2f} > {EXTREME_MULT}x avg={atr_avg:.2f}) — skip H1")
                elif not auto_trade_enabled:
                    log.warning("[H1] Auto-trading disattivato dalla UI — riabilita il toggle sul sito")
                else:
                    can, reason = state.can_trade(now_utc)
                    if not can:
                        log.info(f"[H1] Trade non permesso: {reason}")
                    elif count_open_positions() >= MAX_OPEN_ORDERS:
                        log.info(f"[H1] Max posizioni aperte ({MAX_OPEN_ORDERS})")
                    else:
                        # ── Segnale primario H1 ───────────────────────────────
                        hour = bar_dt.hour

                        # Use Strategy Selector result if available
                        if current_selector_result and strategy_selector:
                            sel_id = current_selector_result["selected_strategy"]
                            sel_tf = current_selector_result["timeframe"]
                            sel_conf = current_selector_result["confidence"]
                            sel_tp_mult = current_selector_result.get("tp_atr_mult", 2.0)
                            sel_sl_mult = current_selector_result.get("sl_atr_mult", 1.0)
                            # Only proceed here if selector chose an H1 strategy
                            fn_sel = SIGNAL_FNS.get(sel_id)
                            if sel_tf == 'H1' and fn_sel:
                                if sel_id == 'S16_GOLDEN_SQUEEZE':
                                    _h4t = cached_I_h4['st'][len(cached_candles_h4)-2] if cached_I_h4 and cached_candles_h4 else None
                                    # Fix 2026-09-02: `hour` mancante → filtro sessione 7-18 UTC bypassato (vedi get_signal)
                                    direction = fn_sel(I_h1, i_h1, h1_trend=I_h1['st'][i_h1], h4_trend=_h4t, hour=hour)
                                elif sel_id in ('S05_MFKK_INTRADAY', 'S09_MFKK_SCALPING', 'S10_OB_FVG_SCALP', 'S17_CONVERGENCE_SCALP'):
                                    direction = fn_sel(I_h1, i_h1, h1_trend=I_h1['st'][i_h1], hour=hour)
                                else:
                                    direction = fn_sel(I_h1, i_h1, hour=hour)
                                strategy_name = sel_id if direction else None
                            else:
                                strategy_name, direction = get_signal(I_h1, i_h1, hour, current_regime)
                                sel_conf = current_selector_result["confidence"]
                                sel_tp_mult = current_selector_result.get("tp_atr_mult", 2.0)
                                sel_sl_mult = current_selector_result.get("sl_atr_mult", 1.0)
                        else:
                            strategy_name, direction = get_signal(I_h1, i_h1, hour, current_regime)
                            sel_conf = last_ai_score / 100.0
                            sel_tp_mult = STRATEGY_PARAMS.get(strategy_name or 'S00_MFKK', {}).get('tp_mult', 2.0)
                            sel_sl_mult = STRATEGY_PARAMS.get(strategy_name or 'S00_MFKK', {}).get('sl_mult', 1.0)

                        if strategy_name is None:
                            log.info(f"Regime: {current_regime} | Nessun segnale primario H1 su {bar_dt.strftime('%H:%M')}")
                        elif has_open_position_for_strategy(strategy_name):
                            log.debug(f"[H1] skip {strategy_name} — già 1 ordine aperto per questa strategia")
                        elif has_position_in_direction(direction):
                            log.info(f"[H1] skip {strategy_name} — già 1 posizione {direction.upper()} aperta (correlazione direzionale)")
                        elif current_news_risk.get('paused'):
                            log.warning(f"⛔ SEGNALE H1 SOSPESO (News) | {strategy_name} | {current_news_risk['reason']}")
                        elif count_open_positions() >= MAX_OPEN_ORDERS:
                            log.info(f"⏸ H1 skip {strategy_name} — max ordini aperti ({MAX_OPEN_ORDERS}) raggiunto")
                        elif sl_cooldowns_until.get(strategy_name) and datetime.datetime.now(datetime.timezone.utc) < sl_cooldowns_until[strategy_name]:
                            remaining = int((sl_cooldowns_until[strategy_name] - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 60)
                            log.warning(f"🛑 H1 skip {strategy_name} — cooldown SL strategico ({remaining}min rimanenti)")
                        elif sl_cooldown_until and datetime.datetime.now(datetime.timezone.utc) < sl_cooldown_until:
                            remaining = int((sl_cooldown_until - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 60)
                            log.warning(f"🛑 H1 skip {strategy_name} — cooldown SL globale ({remaining}min rimanenti)")
                        elif not quality_gate(strategy_name, direction, I_h1, i_h1):
                            log.info(f"📉 H1 skip {strategy_name} — QUALITY GATE FAILED (no spread/extreme RSI/news)")
                        else:
                            atr_i = I_h1['atr'][i_h1] or 10.0
                            base_tp = round(atr_i * sel_tp_mult, 2)
                            base_sl = round(atr_i * sel_sl_mult, 2)

                            # ── RISK GUARDIAN (primary) or RiskManager (fallback) ──
                            rp = None
                            if rg:
                                acc_now = get_account_info()
                                rp = rg.get_order_params(
                                    strategy_confidence=sel_conf,
                                    atr=atr_i,
                                    strategy_id=strategy_name,
                                    ai_score=last_ai_score,
                                    atr_avg=I_h1['atr_avg'][i_h1],
                                    adx=I_h1['adx'][i_h1],
                                    dip=I_h1['dip'][i_h1],
                                    dim=I_h1['dim'][i_h1],
                                    hour_utc=bar_dt.hour,
                                    today_pnl=state.pnl_today,
                                    current_equity=acc_now['equity'] if acc_now else None,
                                    weekly_dd_pct=weekly_dd_pct,
                                    tp_atr_mult=sel_tp_mult,
                                    sl_atr_mult=sel_sl_mult,
                                    direction=direction,
                                )
                                if rp.get('paused'):
                                    log.info(f"⛔ SEGNALE H1 SOSPESO (Risk Guardian) | {strategy_name}")
                                    continue
                                lot_use = rp['lot']
                                tp_use  = rp['tp_usd']
                                sl_use  = rp['sl_usd']
                            elif rm:
                                rp = rm.get_order_params(
                                    ai_score=last_ai_score, atr=atr_i,
                                    strategy=strategy_name, direction=direction,
                                    atr_avg=I_h1['atr_avg'][i_h1],
                                    adx=I_h1['adx'][i_h1], dip=I_h1['dip'][i_h1],
                                    dim=I_h1['dim'][i_h1], hour_utc=bar_dt.hour
                                )
                                if rp.get('paused'):
                                    log.info(f"⛔ SEGNALE H1 SOSPESO (RiskManager) | {strategy_name}")
                                    continue
                                lot_use = rp['lot']
                                tp_use  = base_tp
                                sl_use  = base_sl
                            else:
                                lot_use = LOT_SIZE
                                tp_use  = base_tp
                                sl_use  = base_sl

                            # ── News risk_mult: riduce lot se news media importanza ──
                            news_mult = current_news_risk.get('risk_mult', 1.0)
                            if news_mult < 1.0:
                                lot_use = max(0.01, round(lot_use * news_mult, 2))
                                log.info(f"[NewsGuardian] Lot ridotto ×{news_mult:.0%} → {lot_use} | {current_news_risk['reason']}")

                            params = STRATEGY_PARAMS.get(strategy_name, STRATEGY_PARAMS.get('S00_MFKK', {}))
                            log.info(
                                f"★ SEGNALE H1: {direction.upper()} | {params.get('label', strategy_name)} "
                                f"| Regime: {current_regime} | score={last_ai_score:.0f} "
                                f"| tier={rp.get('tier_label','N/A') if rp else 'FIXED'} "
                                f"| lot={lot_use} | TP=${tp_use:.2f} | SL=${sl_use:.2f}"
                            )

                            result = place_order(
                                direction, tp_use, sl_use, strategy_name,
                                lot_size=lot_use,
                                key_levels_result=current_levels_result,
                                atr=atr_i,
                            )
                            if result:
                                # Tracking in-memory immediato (PRIMA di qualsiasi altro codice)
                                # result.order = order ticket = position ticket in hedging
                                order_ticket = getattr(result, 'order', 0)
                                _strategy_order_tickets[strategy_name] = (order_ticket, direction)
                                state.record_trade(0, now_utc)
                                # Register with Risk Guardian for lifecycle management
                                if rg and rp:
                                    try:
                                        _kl_targets = (current_levels_result or {}).get(
                                            "resistance" if direction == "buy" else "support", []
                                        )[:3]
                                        rg.register_position(
                                            order_ticket, rp, strategy_name, 'H1',
                                            current_regime, direction,
                                            partial_targets=_kl_targets,
                                        )
                                    except Exception as _rg_err:
                                        log.warning(f"[H1] register_position error: {_rg_err}")
                                tick = mt5.symbol_info_tick(SYMBOL)
                                price = tick.ask if direction=='buy' else tick.bid if tick else 0
                                log_trade_to_json(direction, strategy_name, price,
                                                  round(price+(tp_use if direction=='buy' else -tp_use),2),
                                                  round(price-(sl_use if direction=='buy' else -sl_use),2), result)
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
                            if count_open_positions() >= MAX_OPEN_ORDERS: break
                            if sec_id in _strategy_order_tickets and _strategy_order_tickets[sec_id][0]:
                                log.debug(f"[H1sec] skip {sec_id} — ticket già in memoria"); break
                            if sl_cooldowns_until.get(sec_id) and datetime.datetime.now(datetime.timezone.utc) < sl_cooldowns_until[sec_id]: continue
                            if sl_cooldown_until and datetime.datetime.now(datetime.timezone.utc) < sl_cooldown_until: break
                            if MAX_TRADES > 0 and state.trades_today >= MAX_TRADES: break
                            fn2 = SIGNAL_FNS.get(sec_id)
                            if not fn2: continue
                            
                            # Supporto per session hour e h1_trend se richiesto dalla strategia
                            if sec_id == 'S16_GOLDEN_SQUEEZE':
                                _h4t = cached_I_h4['st'][len(cached_candles_h4)-2] if cached_I_h4 and cached_candles_h4 else None
                                sec_dir = fn2(I_h1, i_h1, h1_trend=I_h1['st'][i_h1], h4_trend=_h4t, hour=hour)
                            elif sec_id == 'S00_MFKK':
                                sec_dir = fn2(I_h1, i_h1, hour=hour, tf='H1')
                            elif sec_id in ('S05_MFKK_INTRADAY', 'S09_MFKK_SCALPING', 'S10_OB_FVG_SCALP', 'S17_CONVERGENCE_SCALP'):
                                sec_dir = fn2(I_h1, i_h1, h1_trend=I_h1['st'][i_h1], hour=hour)
                            else:
                                sec_dir = fn2(I_h1, i_h1, hour=hour)
                            if not sec_dir: continue
                            if not quality_gate(sec_id, sec_dir, I_h1, i_h1): continue
                            if sec_dir_filter and sec_dir != sec_dir_filter: continue
                            if has_open_position_for_strategy(sec_id): continue
                            if has_position_in_direction(sec_dir):
                                log.info(f"[H1sec] skip {sec_id} — già 1 posizione {sec_dir.upper()} aperta (correlazione direzionale)")
                                continue

                            # ── CALCOLO TP/SL DI STRATEGIA (SEC) ─────────────
                            sec_params = STRATEGY_PARAMS.get(sec_id, {'tp_usd': 20.0, 'sl_usd': 12.0, 'label': sec_id})
                            base_tp2 = 20.0; base_sl2 = 12.0
                            atr_i2 = I_h1['atr'][i_h1] if I_h1['atr'][i_h1] else None
                            if sec_params.get('tp_usd') == 'ATR' and atr_i2:
                                base_tp2 = atr_i2 * sec_params.get('tp_mult', 1.5)
                            elif isinstance(sec_params.get('tp_usd'), (int, float)):
                                base_tp2 = sec_params['tp_usd']
                            
                            if sec_params.get('sl_usd') == 'ATR' and atr_i2:
                                base_sl2 = atr_i2 * sec_params.get('sl_mult', 1.0)
                            elif isinstance(sec_params.get('sl_usd'), (int, float)):
                                base_sl2 = sec_params['sl_usd']

                            rp2 = None
                            if rg:
                                acc_now = get_account_info()
                                _sec_conf = current_selector_result['confidence'] if current_selector_result else last_ai_score / 100.0
                                rp2 = rg.get_order_params(
                                    strategy_confidence=_sec_conf,
                                    atr=atr_i2, strategy_id=sec_id, ai_score=last_ai_score,
                                    atr_avg=I_h1['atr_avg'][i_h1], adx=I_h1['adx'][i_h1],
                                    dip=I_h1['dip'][i_h1], dim=I_h1['dim'][i_h1], hour_utc=bar_dt.hour,
                                    today_pnl=state.pnl_today,
                                    current_equity=acc_now['equity'] if acc_now else None,
                                    weekly_dd_pct=weekly_dd_pct,
                                    tp_atr_mult=sec_params.get('tp_mult', 1.5),
                                    sl_atr_mult=sec_params.get('sl_mult', 1.0),
                                    direction=sec_dir,
                                )
                                if rp2.get('paused'):
                                    log.info(f"⛔ SEGNALE H1 (sec) SOSPESO (Risk Guardian) | {sec_id}")
                                    continue
                                lot2, tp2, sl2 = rp2['lot'], rp2['tp_usd'], rp2['sl_usd']
                                log.info(f"★ SEGNALE H1 (sec): {sec_dir.upper()} | {sec_params.get('label',sec_id)} | tier={rp2.get('tier_label','N/A')} | lot={lot2} | TP=${tp2:.2f} | SL=${sl2:.2f}")
                            elif rm:
                                rp2 = rm.get_order_params(
                                    ai_score=last_ai_score, atr=atr_i2, strategy=sec_id, direction=sec_dir,
                                    atr_avg=I_h1['atr_avg'][i_h1], adx=I_h1['adx'][i_h1],
                                    dip=I_h1['dip'][i_h1], dim=I_h1['dim'][i_h1], hour_utc=bar_dt.hour
                                )
                                if rp2.get('paused'):
                                    log.info(f"⛔ SEGNALE H1 (sec) SOSPESO (manipolazione) | {sec_id}")
                                    continue
                                lot2, tp2, sl2 = rp2['lot'], base_tp2, base_sl2
                                log.info(f"★ SEGNALE H1 (sec): {sec_dir.upper()} | {sec_params.get('label',sec_id)} | {rp2['tier_label']} manip={rp2['manip_mult']:.2f} | lot={lot2} | TP=${tp2:.2f} | SL=${sl2:.2f}")
                            else:
                                lot2, tp2, sl2 = LOT_SIZE, base_tp2, base_sl2
                                log.info(f"★ SEGNALE H1 (sec): {sec_dir.upper()} | {sec_params.get('label',sec_id)} | lot={lot2} | TP=${tp2:.2f} | SL=${sl2:.2f}")
                            result2 = place_order(sec_dir, tp2, sl2, sec_id, lot_size=lot2,
                                                  key_levels_result=current_levels_result,
                                                  atr=atr_i2)
                            if result2:
                                order_ticket2 = getattr(result2, 'order', 0)
                                _strategy_order_tickets[sec_id] = (order_ticket2, sec_dir)
                                state.record_trade(0, now_utc)
                                if rg and rp2:
                                    try:
                                        _kl_targets2 = (current_levels_result or {}).get(
                                            "resistance" if sec_dir == "buy" else "support", []
                                        )[:3]
                                        rg.register_position(
                                            order_ticket2, rp2, sec_id, 'H1',
                                            current_regime, sec_dir,
                                            partial_targets=_kl_targets2,
                                        )
                                    except Exception as _rg_err:
                                        log.warning(f"[H1sec] register_position error: {_rg_err}")
                                tick2 = mt5.symbol_info_tick(SYMBOL)
                                price2 = tick2.ask if sec_dir=='buy' else tick2.bid if tick2 else 0
                                log_trade_to_json(sec_dir, sec_id, price2,
                                                  round(price2+(tp2 if sec_dir=='buy' else -tp2),2),
                                                  round(price2-(sl2 if sec_dir=='buy' else -sl2),2), result2)

            # ── LIVE SIGNAL SCAN: candela corrente H1/M30 (dedup per barra, ogni 60s) ──────
            # Replica il browser: rileva segnali sulla candle live senza aspettare la chiusura.
            # Dedup key = (strat, dir, tf, bar_open_time) — non ri-esegue sulla stessa barra.
            if auto_trade_enabled and not current_is_extreme and cached_I_h1 is not None:
                _pb_l = PLAYBOOK.get(current_regime, {})
                _sn_l = _pb_l.get('strategy', 'S00_MFKK')
                _tf_l = _pb_l.get('tf', 'M30')
                _fn_l = SIGNAL_FNS.get(_sn_l)
                _h1_trend_l = cached_I_h1['st'][len(candles)-2] if 'st' in cached_I_h1 else 0

                _I_l, _i_l, _bt_l = None, None, None
                if _tf_l == 'H1':
                    _I_l  = cached_I_h1
                    _i_l  = len(candles) - 1
                    _bt_l = candles[-1]['t']
                else:  # M30 o M15 → aggiorna cache M30 ogni 60s
                    if now_ts - _m30_live_ts >= 60:
                        _mc = get_candles_tf('M30', 200)
                        if _mc and len(_mc) >= 50:
                            _m30_live_cnds  = _mc
                            _m30_live_cache = compute_indicators(_mc)
                            _m30_live_ts    = now_ts
                    if _m30_live_cache is not None and _m30_live_cnds:
                        _I_l  = _m30_live_cache
                        _i_l  = len(_m30_live_cnds) - 1
                        _bt_l = _m30_live_cnds[-1]['t']

                if _fn_l and _I_l is not None and _i_l is not None and _bt_l is not None:
                    _h_l = now_utc.hour
                    if _sn_l == 'S05_MFKK_INTRADAY':
                        _d_l = _fn_l(_I_l, _i_l, h1_trend=_I_l['st'][_i_l], hour=_h_l)
                    elif _sn_l == 'S00_MFKK':
                        _d_l = _fn_l(_I_l, _i_l, hour=_h_l, tf=_tf_l)
                    elif _sn_l in ('S09_MFKK_SCALPING', 'S10_OB_FVG_SCALP', 'S17_CONVERGENCE_SCALP'):
                        _d_l = _fn_l(_I_l, _i_l, h1_trend=_h1_trend_l, hour=_h_l)
                    else:
                        _d_l = _fn_l(_I_l, _i_l, hour=_h_l)

                    if _d_l:
                        _lk = (_sn_l, _d_l, _tf_l, _bt_l)
                        if _lk not in _live_dedup:
                            _can_l, _ = state.can_trade(now_utc)
                            _now_u = datetime.datetime.now(datetime.timezone.utc)
                            if (_can_l
                                    and count_open_positions() < MAX_OPEN_ORDERS
                                    and not has_open_position_for_strategy(_sn_l)
                                    and not has_position_in_direction(_d_l)
                                    and not current_news_risk.get('paused')
                                    and not (sl_cooldowns_until.get(_sn_l) and _now_u < sl_cooldowns_until[_sn_l])
                                    and not (sl_cooldown_until and _now_u < sl_cooldown_until)
                                    and quality_gate(_sn_l, _d_l, _I_l, _i_l)):
                                _live_dedup.add(_lk)
                                if len(_live_dedup) > 200: _live_dedup.clear()
                                _atr_l = _I_l['atr'][_i_l] or 10.0
                                _pm_l  = STRATEGY_PARAMS.get(_sn_l, STRATEGY_PARAMS.get('S00_MFKK', {}))
                                _tp_l  = round(_atr_l * _pm_l.get('tp_mult', 2.0), 2)
                                _sl_l  = round(_atr_l * _pm_l.get('sl_mult', 1.0), 2)
                                _rp_l  = None
                                if rg:
                                    _ac_l = get_account_info()
                                    _cf_l = current_selector_result['confidence'] if current_selector_result else last_ai_score / 100.0
                                    _rp_l = rg.get_order_params(
                                        strategy_confidence=_cf_l, atr=_atr_l,
                                        strategy_id=_sn_l, ai_score=last_ai_score,
                                        atr_avg=_I_l['atr_avg'][_i_l],
                                        adx=_I_l['adx'][_i_l], dip=_I_l['dip'][_i_l],
                                        dim=_I_l['dim'][_i_l], hour_utc=_h_l,
                                        today_pnl=state.pnl_today,
                                        current_equity=_ac_l['equity'] if _ac_l else None,
                                        weekly_dd_pct=weekly_dd_pct,
                                        tp_atr_mult=_pm_l.get('tp_mult', 2.0),
                                        sl_atr_mult=_pm_l.get('sl_mult', 1.0),
                                        direction=_d_l,
                                    )
                                    if _rp_l and _rp_l.get('paused'):
                                        log.info(f"⛔ LIVE {_tf_l} SOSPESO (RiskGuardian) | {_sn_l}")
                                        _rp_l = None
                                if _rp_l is not None or not rg:
                                    _lot_l = _rp_l['lot'] if _rp_l else LOT_SIZE
                                    _tp_lu = _rp_l['tp_usd'] if _rp_l else _tp_l
                                    _sl_lu = _rp_l['sl_usd'] if _rp_l else _sl_l
                                    log.info(f"★ LIVE {_tf_l} [{_sn_l}]: {_d_l.upper()} | lot={_lot_l} | TP=${_tp_lu:.2f} | SL=${_sl_lu:.2f}")
                                    _res_l = place_order(_d_l, _tp_lu, _sl_lu, _sn_l,
                                                         lot_size=_lot_l,
                                                         key_levels_result=current_levels_result,
                                                         atr=_atr_l)
                                    if _res_l:
                                        _strategy_order_tickets[_sn_l] = (getattr(_res_l, 'order', 0), _d_l)
                                        state.record_trade(0, now_utc)
                                        if rg and _rp_l:
                                            try:
                                                rg.register_position(getattr(_res_l, 'order', 0), _rp_l,
                                                                      _sn_l, _tf_l, current_regime, _d_l)
                                            except Exception: pass
                                        sync_to_vercel(
                                            get_account_info(), get_open_positions_data(),
                                            get_recent_trades_data(200),
                                            {'running': True, 'dry_run': DRY_RUN, 'symbol': SYMBOL, 'lot': LOT_SIZE,
                                             'trades_today': state.trades_today, 'pnl_today': state.pnl_today,
                                             'regime': current_regime, 'last_signal': _sn_l}
                                        )
                                        last_sync_time = time.time()

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
                        elif count_open_positions() >= MAX_OPEN_ORDERS:
                            log.debug(f"[M15] Max posizioni aperte ({MAX_OPEN_ORDERS})")
                        elif sl_cooldowns_until.get(pb_entry['strategy']) and datetime.datetime.now(datetime.timezone.utc) < sl_cooldowns_until[pb_entry['strategy']]:
                            remaining = int((sl_cooldowns_until[pb_entry['strategy']] - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 60)
                            log.warning(f"🛑 M15 skip — cooldown SL strategico ({remaining}min rimanenti)")
                        elif sl_cooldown_until and datetime.datetime.now(datetime.timezone.utc) < sl_cooldown_until:
                            remaining = int((sl_cooldown_until - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 60)
                            log.warning(f"🛑 M15 skip — cooldown SL globale ({remaining}min rimanenti)")
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
                                _h4t = cached_I_h4['st'][len(cached_candles_h4)-2] if cached_I_h4 and cached_candles_h4 else None
                                # Fix 2026-09-02: `hour` mancante → filtro sessione 7-18 UTC bypassato (vedi get_signal)
                                direction = fn(I_m15, idx, h1_trend=curr_h1_trend, h4_trend=_h4t, hour=bar_dt_m15.hour)
                            elif sname in ('S05_MFKK_INTRADAY', 'S09_MFKK_SCALPING', 'S10_OB_FVG_SCALP', 'S17_CONVERGENCE_SCALP'):
                                direction = fn(I_m15, idx, h1_trend=curr_h1_trend, hour=bar_dt_m15.hour) if fn else None
                            else:
                                direction = fn(I_m15, idx) if fn else None

                            if direction and has_open_position_for_strategy(sname):
                                log.debug(f"[M15] skip {sname} — già 1 ordine aperto per questa strategia")
                            elif direction and has_position_in_direction(direction):
                                log.info(f"[M15] skip {sname} — già 1 posizione {direction.upper()} aperta (correlazione direzionale)")
                            elif direction and current_news_risk.get('paused'):
                                log.warning(f"⛔ SEGNALE M15 SOSPESO (News) | {sname} | {current_news_risk['reason']}")
                            elif direction and not quality_gate(sname, direction, I_m15, idx):
                                log.info(f"📉 M15 skip {sname} — QUALITY GATE FAILED")
                            elif direction:
                                # ── CALCOLO TP/SL DI STRATEGIA (M15) ────────────
                                params = STRATEGY_PARAMS.get(sname, {'tp_usd': 15.0, 'sl_usd': 10.0, 'label': sname})
                                atr_i = I_m15['atr'][idx] if I_m15['atr'][idx] else None
                                base_tp_m15 = 15.0; base_sl_m15 = 10.0
                                if params.get('tp_usd') == 'ATR' and atr_i:
                                    base_tp_m15 = atr_i * params.get('tp_mult', 1.5)
                                elif isinstance(params.get('tp_usd'), (int, float)):
                                    base_tp_m15 = params['tp_usd']
                                
                                if params.get('sl_usd') == 'ATR' and atr_i:
                                    base_sl_m15 = atr_i * params.get('sl_mult', 1.0)
                                elif isinstance(params.get('sl_usd'), (int, float)):
                                    base_sl_m15 = params['sl_usd']

                                rp = None
                                if rg:
                                    acc_now = get_account_info()
                                    _sel_conf_m15 = current_selector_result['confidence'] if current_selector_result else last_ai_score / 100.0
                                    rp = rg.get_order_params(
                                        strategy_confidence=_sel_conf_m15,
                                        atr=atr_i, strategy_id=sname, ai_score=last_ai_score,
                                        atr_avg=I_m15.get('atr_avg', [None]*len(candles_m15))[idx],
                                        adx=I_m15['adx'][idx], dip=I_m15['dip'][idx],
                                        dim=I_m15['dim'][idx], hour_utc=bar_dt_m15.hour,
                                        today_pnl=state.pnl_today,
                                        current_equity=acc_now['equity'] if acc_now else None,
                                        weekly_dd_pct=weekly_dd_pct,
                                        tp_atr_mult=params.get('tp_mult', 1.5),
                                        sl_atr_mult=params.get('sl_mult', 1.0),
                                        direction=direction,
                                    )
                                    if rp.get('paused'):
                                        log.info(f"⛔ SEGNALE M15 SOSPESO (Risk Guardian) | {sname}")
                                        continue
                                    lot_use, tp_use, sl_use = rp['lot'], rp['tp_usd'], rp['sl_usd']
                                    log.info(f"★ SEGNALE M15: {direction.upper()} | {params['label']} | Regime: {current_regime} | tier={rp.get('tier_label','N/A')} | lot={lot_use} | TP=${tp_use:.2f} | SL=${sl_use:.2f}")
                                elif rm:
                                    rp = rm.get_order_params(
                                        ai_score=last_ai_score, atr=atr_i, strategy=sname, direction=direction,
                                        atr_avg=I_m15.get('atr_avg', [None]*len(candles_m15))[idx],
                                        adx=I_m15['adx'][idx], dip=I_m15['dip'][idx],
                                        dim=I_m15['dim'][idx], hour_utc=bar_dt_m15.hour
                                    )
                                    if rp.get('paused'):
                                        log.info(f"⛔ SEGNALE M15 SOSPESO (manipolazione) | {sname}")
                                        continue
                                    lot_use, tp_use, sl_use = rp['lot'], base_tp_m15, base_sl_m15
                                    log.info(f"★ SEGNALE M15: {direction.upper()} | {params['label']} | Regime: {current_regime} | {rp['tier_label']} manip={rp['manip_mult']:.2f} | lot={lot_use} | TP=${tp_use:.2f} | SL=${sl_use:.2f}")
                                else:
                                    lot_use, tp_use, sl_use = LOT_SIZE, base_tp_m15, base_sl_m15
                                    log.info(f"★ SEGNALE M15: {direction.upper()} | {params['label']} | Regime: {current_regime} | lot={lot_use} | TP=${tp_use:.2f} | SL=${sl_use:.2f}")
                                
                                result = place_order(direction, tp_use, sl_use, sname, lot_size=lot_use,
                                                    key_levels_result=current_levels_result,
                                                    atr=atr_now)
                                if result:
                                    order_ticket_m15 = getattr(result, 'order', 0)
                                    _strategy_order_tickets[sname] = (order_ticket_m15, direction)
                                    state.record_trade(0, now_utc)
                                    if rg and rp:
                                        try:
                                            _kl_targets = (current_levels_result or {}).get(
                                                "resistance" if direction == "buy" else "support", []
                                            )[:3]
                                            rg.register_position(
                                                order_ticket_m15, rp, sname, 'M15',
                                                current_regime, direction,
                                                partial_targets=_kl_targets,
                                            )
                                        except Exception as _rg_err:
                                            log.warning(f"[M15] register_position error: {_rg_err}")
                                    tick = mt5.symbol_info_tick(SYMBOL)
                                    price = tick.ask if direction=='buy' else tick.bid if tick else 0
                                    log_trade_to_json(direction, sname, price,
                                                      round(price+(tp_use if direction=='buy' else -tp_use),2),
                                                      round(price-(sl_use if direction=='buy' else -sl_use),2), result)
                                    acc = get_account_info()
                                    if acc: log.info(f"Account aggiornato: {acc['equity']:.2f} {acc['currency']}")
                                    sync_to_vercel(acc, get_open_positions_data(), get_recent_trades_data(200),
                                                   {'running':True,'dry_run':DRY_RUN,'symbol':SYMBOL,'lot':LOT_SIZE,
                                                    'trades_today':state.trades_today,'pnl_today':state.pnl_today,
                                                    'regime':current_regime,'last_signal':sname})
                                    last_sync_time = time.time()
                            else:
                                log.info(f"[M15] Regime: {current_regime} | Nessun segnale su {bar_dt_m15.strftime('%H:%M')}")

            # ── Controlla nuova candela M30 — tutte le strategie M30 del regime ──
            # IMPORTANTE: usa 'if' indipendente (NON elif) — deve girare in parallelo a M15.
            # BUG#1 fix 2026-04-23: era 'elif' → bloccava M30 quando playbook usava M15.
            if not current_is_extreme:
                candles_m30 = get_candles_tf('M30', 450)
                if candles_m30 and len(candles_m30) >= 50:
                    latest_m30 = candles_m30[-2]['t']
                    if latest_m30 != last_bar_time_m30:
                        last_bar_time_m30 = latest_m30
                        bar_dt_m30 = datetime.datetime.fromtimestamp(latest_m30, tz=datetime.timezone.utc)
                        log.info(f"─── Nuova barra M30 chiusa: {bar_dt_m30.strftime('%Y-%m-%d %H:%M')} UTC ───")
                        can, reason = state.can_trade(now_utc)
                        if not auto_trade_enabled:
                            log.warning("[M30] Auto-trading disattivato dalla UI — riabilita il toggle sul sito")
                        elif not can:
                            log.info(f"[M30] Trade non permesso: {reason}")
                        elif count_open_positions() >= MAX_OPEN_ORDERS:
                            log.info(f"[M30] Max posizioni aperte ({MAX_OPEN_ORDERS})")
                        elif sl_cooldown_until and datetime.datetime.now(datetime.timezone.utc) < sl_cooldown_until:
                            remaining = int((sl_cooldown_until - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 60)
                            log.warning(f"🛑 M30 skip — cooldown SL attivo ({remaining}min rimanenti)")
                        else:
                            I_m30 = compute_indicators(candles_m30)
                            idx = len(candles_m30) - 2
                            curr_h1_trend = I_h1['st'][i_h1] if 'st' in I_h1 else 0

                            _m30_entries = [(s, d) for (s, t, d) in REGIME_MULTI_STRATEGIES.get(current_regime, []) if t == 'M30']
                            if not _m30_entries:
                                _m30_entries = [(pb_entry['strategy'], None)]

                            for (sname, m30_dir_filter) in _m30_entries:
                                if count_open_positions() >= MAX_OPEN_ORDERS: break
                                # Guard pre-segnale: blocca subito se il ticket è già in memoria
                                # (difesa contro race-condition MT5 dove positions_get() è lento)
                                if sname in _strategy_order_tickets and _strategy_order_tickets[sname][0]:
                                    log.debug(f"[M30] skip {sname} — ticket già in memoria")
                                    break
                                if sl_cooldown_until and datetime.datetime.now(datetime.timezone.utc) < sl_cooldown_until: break
                                if sl_cooldowns_until.get(sname) and datetime.datetime.now(datetime.timezone.utc) < sl_cooldowns_until[sname]:
                                    remaining = int((sl_cooldowns_until[sname] - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 60)
                                    log.warning(f"🛑 M30 skip {sname} — cooldown SL strategico ({remaining}min rimanenti)")
                                    continue

                                sf = SESSION_FILTER.get(sname)
                                if sf and bar_dt_m30.hour in sf['block_hours']:
                                    log.info(f"[M30] {sname} saltato — sessione ({bar_dt_m30.strftime('%H:%M')} UTC)")
                                    continue

                                fn = SIGNAL_FNS.get(sname)
                                if not fn: continue

                                if sname == 'S16_GOLDEN_SQUEEZE':
                                    _h4t = cached_I_h4['st'][len(cached_candles_h4)-2] if cached_I_h4 and cached_candles_h4 else None
                                    direction = fn(I_m30, idx, h1_trend=curr_h1_trend, h4_trend=_h4t, hour=bar_dt_m30.hour)
                                elif sname == 'S00_MFKK':
                                    direction = fn(I_m30, idx, hour=bar_dt_m30.hour, tf='M30')
                                elif sname in ('S05_MFKK_INTRADAY', 'S09_MFKK_SCALPING', 'S10_OB_FVG_SCALP', 'S17_CONVERGENCE_SCALP'):
                                    direction = fn(I_m30, idx, h1_trend=curr_h1_trend, hour=bar_dt_m30.hour)
                                else:
                                    direction = fn(I_m30, idx, hour=bar_dt_m30.hour)

                                if not direction:
                                    log.info(f"[M30] {sname} — nessun segnale ({bar_dt_m30.strftime('%H:%M')})")
                                    continue
                                if m30_dir_filter and direction != m30_dir_filter: continue
                                if not quality_gate(sname, direction, I_m30, idx):
                                    log.info(f"📉 M30 skip {sname} — QUALITY GATE FAILED")
                                    continue
                                if has_open_position_for_strategy(sname):
                                    log.debug(f"[M30] skip {sname} — già aperto")
                                    continue
                                if has_position_in_direction(direction):
                                    log.info(f"[M30] skip {sname} — già 1 posizione {direction.upper()} aperta (correlazione direzionale)")
                                    continue
                                if current_news_risk.get('paused'):
                                    log.warning(f"⛔ SEGNALE M30 SOSPESO (News) | {sname} | {current_news_risk['reason']}")
                                    continue

                                params = STRATEGY_PARAMS.get(sname, {'tp_usd': 15.0, 'sl_usd': 10.0, 'label': sname})
                                atr_i = I_m30['atr'][idx] if I_m30['atr'][idx] else None
                                if params.get('tp_usd') == 'ATR' and atr_i:
                                    base_tp_m30 = atr_i * params.get('tp_mult', 1.5)
                                elif isinstance(params.get('tp_usd'), (int, float)):
                                    base_tp_m30 = params['tp_usd']
                                else:
                                    base_tp_m30 = 15.0
                                if params.get('sl_usd') == 'ATR' and atr_i:
                                    base_sl_m30 = atr_i * params.get('sl_mult', 1.0)
                                elif isinstance(params.get('sl_usd'), (int, float)):
                                    base_sl_m30 = params['sl_usd']
                                else:
                                    base_sl_m30 = 10.0

                                rp = None
                                if rg:
                                    acc_now = get_account_info()
                                    _sel_conf_m30 = current_selector_result['confidence'] if current_selector_result else last_ai_score / 100.0
                                    rp = rg.get_order_params(
                                        strategy_confidence=_sel_conf_m30,
                                        atr=atr_i, strategy_id=sname, ai_score=last_ai_score,
                                        atr_avg=I_m30.get('atr_avg', [None]*len(candles_m30))[idx],
                                        adx=I_m30['adx'][idx], dip=I_m30['dip'][idx],
                                        dim=I_m30['dim'][idx], hour_utc=bar_dt_m30.hour,
                                        today_pnl=state.pnl_today,
                                        current_equity=acc_now['equity'] if acc_now else None,
                                        weekly_dd_pct=weekly_dd_pct,
                                        tp_atr_mult=params.get('tp_mult', 1.5),
                                        sl_atr_mult=params.get('sl_mult', 1.0),
                                        direction=direction,
                                    )
                                    if rp.get('paused'):
                                        log.info(f"⛔ SEGNALE M30 SOSPESO (Risk Guardian) | {sname}")
                                        continue
                                    lot_use, tp_use, sl_use = rp['lot'], rp['tp_usd'], rp['sl_usd']
                                    log.info(f"★ SEGNALE M30: {direction.upper()} | {params['label']} | Regime: {current_regime} | tier={rp.get('tier_label','N/A')} | lot={lot_use} | TP=${tp_use:.2f} | SL=${sl_use:.2f}")
                                elif rm:
                                    rp = rm.get_order_params(
                                        ai_score=last_ai_score, atr=atr_i, strategy=sname, direction=direction,
                                        atr_avg=I_m30.get('atr_avg', [None]*len(candles_m30))[idx],
                                        adx=I_m30['adx'][idx], dip=I_m30['dip'][idx],
                                        dim=I_m30['dim'][idx], hour_utc=bar_dt_m30.hour
                                    )
                                    if rp.get('paused'):
                                        log.info(f"⛔ SEGNALE M30 SOSPESO (manipolazione) | {sname}")
                                        continue
                                    lot_use, tp_use, sl_use = rp['lot'], base_tp_m30, base_sl_m30
                                    log.info(f"★ SEGNALE M30: {direction.upper()} | {params['label']} | Regime: {current_regime} | {rp['tier_label']} | lot={lot_use} | TP=${tp_use:.2f} | SL=${sl_use:.2f}")
                                else:
                                    lot_use, tp_use, sl_use = LOT_SIZE, base_tp_m30, base_sl_m30
                                    log.info(f"★ SEGNALE M30: {direction.upper()} | {params['label']} | Regime: {current_regime} | lot={lot_use} | TP=${tp_use:.2f} | SL=${sl_use:.2f}")

                                result = place_order(direction, tp_use, sl_use, sname, lot_size=lot_use,
                                                    key_levels_result=current_levels_result,
                                                    atr=atr_now)
                                if result:
                                    order_ticket_m30 = getattr(result, 'order', 0)
                                    _strategy_order_tickets[sname] = (order_ticket_m30, direction)
                                    state.record_trade(0, now_utc)
                                    if rg and rp:
                                        try:
                                            _kl_targets = (current_levels_result or {}).get(
                                                "resistance" if direction == "buy" else "support", []
                                            )[:3]
                                            rg.register_position(
                                                order_ticket_m30, rp, sname, 'M30',
                                                current_regime, direction,
                                                partial_targets=_kl_targets,
                                            )
                                        except Exception as _rg_err:
                                            log.warning(f"[M30] register_position error: {_rg_err}")
                                    tick = mt5.symbol_info_tick(SYMBOL)
                                    price = tick.ask if direction=='buy' else tick.bid if tick else 0
                                    log_trade_to_json(direction, sname, price,
                                                      round(price+(tp_use if direction=='buy' else -tp_use),2),
                                                      round(price-(sl_use if direction=='buy' else -sl_use),2), result)
                                    acc = get_account_info()
                                    if acc: log.info(f"Account aggiornato: {acc['equity']:.2f} {acc['currency']}")
                                    sync_to_vercel(acc, get_open_positions_data(), get_recent_trades_data(200),
                                                   {'running':True,'dry_run':DRY_RUN,'symbol':SYMBOL,'lot':LOT_SIZE,
                                                    'trades_today':state.trades_today,'pnl_today':state.pnl_today,
                                                    'regime':current_regime,'last_signal':sname})
                                    last_sync_time = time.time()

            # ── Controlla nuova candela H4 (strategie H4 da REGIME_MULTI_STRATEGIES) ──
            # Gira sempre in parallelo a M30/M15 — non è un elif
            _h4_entries = [(s, d) for (s, t, d) in REGIME_MULTI_STRATEGIES.get(current_regime, []) if t == 'H4']
            if _h4_entries and not current_is_extreme:
                candles_h4 = get_candles_tf('H4', 300)
                if candles_h4 and len(candles_h4) >= 89:
                    latest_h4 = candles_h4[-2]['t']
                    if latest_h4 != last_bar_time_h4:
                        last_bar_time_h4 = latest_h4
                        bar_dt_h4 = datetime.datetime.fromtimestamp(latest_h4, tz=datetime.timezone.utc)
                        log.info(f"─── Nuova barra H4 chiusa: {bar_dt_h4.strftime('%Y-%m-%d %H:%M')} UTC ───")
                        I_h4 = compute_indicators(candles_h4)
                        idx = len(candles_h4) - 2
                        for (h4_id, h4_dir_filter) in _h4_entries:
                            if not auto_trade_enabled:
                                log.warning("[H4] Auto-trading disattivato dalla UI — riabilita il toggle sul sito"); break
                            can, reason = state.can_trade(now_utc)
                            if not can:
                                log.debug(f"[H4] Trade non permesso: {reason}")
                                break
                            if count_open_positions() >= MAX_OPEN_ORDERS:
                                log.debug(f"[H4] Max posizioni aperte ({MAX_OPEN_ORDERS})")
                                break
                            if h4_id in _strategy_order_tickets and _strategy_order_tickets[h4_id][0]:
                                log.debug(f"[H4] skip {h4_id} — ticket già in memoria"); break
                            if sl_cooldown_until and datetime.datetime.now(datetime.timezone.utc) < sl_cooldown_until:
                                remaining = int((sl_cooldown_until - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 60)
                                log.warning(f"🛑 H4 skip {h4_id} — cooldown SL attivo ({remaining}min rimanenti)")
                                break
                            if sl_cooldowns_until.get(h4_id) and datetime.datetime.now(datetime.timezone.utc) < sl_cooldowns_until[h4_id]:
                                remaining = int((sl_cooldowns_until[h4_id] - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 60)
                                log.warning(f"🛑 H4 skip {h4_id} — cooldown SL strategico ({remaining}min rimanenti)")
                                continue
                            fn_h4 = SIGNAL_FNS.get(h4_id)
                            if fn_h4 is None:
                                direction = None
                            elif h4_id == 'S17_CONVERGENCE_SCALP':
                                direction = fn_h4(I_h4, idx, h1_trend=I_h1['st'][i_h1], hour=bar_dt_h4.hour)
                            elif h4_id == 'S00_MFKK':
                                direction = fn_h4(I_h4, idx, hour=bar_dt_h4.hour, tf='H4')
                            else:
                                direction = fn_h4(I_h4, idx, hour=bar_dt_h4.hour)
                            if not direction:
                                log.info(f"[H4] {h4_id} — nessun segnale su {bar_dt_h4.strftime('%H:%M')}")
                                continue
                            if h4_dir_filter and direction != h4_dir_filter:
                                continue
                            if not quality_gate(h4_id, direction, I_h4, idx):
                                log.info(f"📉 H4 skip {h4_id} — QUALITY GATE FAILED")
                                continue
                            if has_open_position_for_strategy(h4_id):
                                log.debug(f"[H4] skip {h4_id} — già 1 ordine aperto")
                                continue
                            if has_position_in_direction(direction):
                                log.info(f"[H4] skip {h4_id} — già 1 posizione {direction.upper()} aperta (correlazione direzionale)")
                                continue
                            if current_news_risk.get('paused'):
                                log.warning(f"⛔ SEGNALE H4 SOSPESO (News) | {h4_id} | {current_news_risk['reason']}")
                                continue
                            params = STRATEGY_PARAMS.get(h4_id, {'tp_usd': 15.0, 'sl_usd': 10.0, 'label': h4_id})
                            atr_i = I_h4['atr'][idx] if I_h4['atr'][idx] else None
                            base_tp_h4 = 15.0; base_sl_h4 = 10.0
                            if params.get('tp_usd') == 'ATR' and atr_i:
                                base_tp_h4 = atr_i * params.get('tp_mult', 1.5)
                            elif isinstance(params.get('tp_usd'), (int, float)):
                                base_tp_h4 = params['tp_usd']
                            if params.get('sl_usd') == 'ATR' and atr_i:
                                base_sl_h4 = atr_i * params.get('sl_mult', 1.0)
                            elif isinstance(params.get('sl_usd'), (int, float)):
                                base_sl_h4 = params['sl_usd']
                            rp = None
                            if rg:
                                acc_now = get_account_info()
                                _sel_conf_h4 = current_selector_result['confidence'] if current_selector_result else last_ai_score / 100.0
                                rp = rg.get_order_params(
                                    strategy_confidence=_sel_conf_h4,
                                    atr=atr_i, strategy_id=h4_id, ai_score=last_ai_score,
                                    atr_avg=I_h4.get('atr_avg', [None]*len(candles_h4))[idx],
                                    adx=I_h4['adx'][idx], dip=I_h4['dip'][idx],
                                    dim=I_h4['dim'][idx], hour_utc=bar_dt_h4.hour,
                                    today_pnl=state.pnl_today,
                                    current_equity=acc_now['equity'] if acc_now else None,
                                    weekly_dd_pct=weekly_dd_pct,
                                    tp_atr_mult=params.get('tp_mult', 2.5),
                                    sl_atr_mult=params.get('sl_mult', 0.8),
                                    direction=direction,
                                )
                                if rp.get('paused'):
                                    log.info(f"⛔ SEGNALE H4 SOSPESO (Risk Guardian) | {h4_id}")
                                    continue
                                lot_use, tp_use, sl_use = rp['lot'], rp['tp_usd'], rp['sl_usd']
                                log.info(f"★ SEGNALE H4: {direction.upper()} | {params.get('label', h4_id)} | Regime: {current_regime} | tier={rp.get('tier_label','N/A')} | lot={lot_use} | TP=${tp_use:.2f} | SL=${sl_use:.2f}")
                            elif rm:
                                rp = rm.get_order_params(
                                    ai_score=last_ai_score, atr=atr_i, strategy=h4_id, direction=direction,
                                    atr_avg=I_h4.get('atr_avg', [None]*len(candles_h4))[idx],
                                    adx=I_h4['adx'][idx], dip=I_h4['dip'][idx],
                                    dim=I_h4['dim'][idx], hour_utc=bar_dt_h4.hour
                                )
                                if rp.get('paused'):
                                    log.info(f"⛔ SEGNALE H4 SOSPESO (manipolazione) | {h4_id}")
                                    continue
                                lot_use, tp_use, sl_use = rp['lot'], base_tp_h4, base_sl_h4
                                log.info(f"★ SEGNALE H4: {direction.upper()} | {params.get('label', h4_id)} | Regime: {current_regime} | {rp['tier_label']} | lot={lot_use} | TP=${tp_use:.2f} | SL=${sl_use:.2f}")
                            else:
                                lot_use, tp_use, sl_use = LOT_SIZE, base_tp_h4, base_sl_h4
                                log.info(f"★ SEGNALE H4: {direction.upper()} | {params.get('label', h4_id)} | Regime: {current_regime} | lot={lot_use} | TP=${tp_use:.2f} | SL=${sl_use:.2f}")
                            result = place_order(direction, tp_use, sl_use, h4_id, lot_size=lot_use,
                                                key_levels_result=current_levels_result, atr=atr_now)
                            if result:
                                order_ticket_h4 = getattr(result, 'order', 0)
                                _strategy_order_tickets[h4_id] = (order_ticket_h4, direction)
                                state.record_trade(0, now_utc)
                                if rg and rp:
                                    try:
                                        _kl_targets = (current_levels_result or {}).get(
                                            "resistance" if direction == "buy" else "support", []
                                        )[:3]
                                        rg.register_position(order_ticket_h4, rp, h4_id, 'H4',
                                                             current_regime, direction,
                                                             partial_targets=_kl_targets)
                                    except Exception as _rg_err:
                                        log.warning(f"[H4] register_position error: {_rg_err}")
                                tick = mt5.symbol_info_tick(SYMBOL)
                                price = tick.ask if direction=='buy' else tick.bid if tick else 0
                                log_trade_to_json(direction, h4_id, price,
                                                  round(price+(tp_use if direction=='buy' else -tp_use),2),
                                                  round(price-(sl_use if direction=='buy' else -sl_use),2), result)
                                acc = get_account_info()
                                if acc: log.info(f"Account aggiornato: {acc['equity']:.2f} {acc['currency']}")
                                sync_to_vercel(acc, get_open_positions_data(), get_recent_trades_data(200),
                                               {'running':True,'dry_run':DRY_RUN,'symbol':SYMBOL,'lot':LOT_SIZE,
                                                'trades_today':state.trades_today,'pnl_today':state.pnl_today,
                                                'regime':current_regime,'last_signal':h4_id})
                                last_sync_time = time.time()

            # ── S20_FIB_CONFLUENCE — segnale M5 proprio (fuori da StrategySelector) ──
            if S20_ENABLED:
                try:
                    s20_manage()
                    s20_check_entry(current_news_risk.get('paused', False), auto_trade_enabled,
                                     weekly_dd_pct=weekly_dd_pct,
                                     news_risk_mult=current_news_risk.get('risk_mult', 1.0),
                                     sl_cooldowns_until=sl_cooldowns_until,
                                     sl_cooldown_until=sl_cooldown_until)
                except Exception as _s20_err:
                    log.warning(f"[S20] errore ciclo: {_s20_err}")

            # ── S30_DOW_DIP — US30 H4, blocco isolato su 2° simbolo ──
            if us30_ok:
                try:
                    _us30_manage()
                    _us30_check_entry(current_news_risk.get('paused', False), auto_trade_enabled)
                except Exception as _s30_err:
                    log.warning(f"[S30] errore ciclo: {_s30_err}")

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
