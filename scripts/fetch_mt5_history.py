#!/usr/bin/env python3
"""
TradeFlow AI — Fetch storico candele da MetaTrader 5 (multi-asset, multi-TF)
Salva i dati in data/{asset}_{tf}_mt5.json (stesso formato usato dal backtester).

USO:
  python scripts/fetch_mt5_history.py                       # XAU H1, 730 giorni (default)
  python scripts/fetch_mt5_history.py --tf M30              # XAU M30
  python scripts/fetch_mt5_history.py --asset us30 --tf H1  # US30 H1
  python scripts/fetch_mt5_history.py --asset us30 --all-tf # US30, tutti i TF M5..D1
  python scripts/fetch_mt5_history.py --days 365 --out custom.json

ASSET:
  xau  → xauusd_{tf}_mt5.json  (simboli: GOLD / XAUUSD / ...)
  us30 → us30_{tf}_mt5.json    (simboli: US30Cash / US30 / DJ30 / ...)

PREREQUISITI:
  pip install MetaTrader5
  MT5 deve essere aperto con l'account configurato sotto.
"""

import sys, io, argparse, json, math, datetime, os
from dotenv import load_dotenv
load_dotenv()
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ── CONFIG (legge da .env, fallback su hardcoded) ───────────────────────────
MT5_LOGIN    = int(os.getenv("MT5_LOGIN", 1301224666))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "Alessandro95!")
MT5_SERVER   = os.getenv("MT5_SERVER", "XMGlobal-MT5 6")

# Candidati simbolo per asset (primo visibile/attivabile vince).
ASSET_SYMBOLS = {
    'xau':  ["GOLD", "XAUUSD", "XAUUSD.m", "XAUUSD_micro"],
    'us30': ["US30Cash", "US30", "US30.cash", "DJ30", "WS30", "US30m", "US30.spot", "DJIUSD"],
}
# Prefisso file per asset (xau resta 'xauusd' per compat con i path esistenti).
ASSET_FILE_PREFIX = {'xau': 'xauusd', 'us30': 'us30'}

# ── ARGPARSE ──────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description='Fetch storico candele da MT5 (multi-asset, multi-TF)')
parser.add_argument('--asset', type=str, default='xau', choices=list(ASSET_SYMBOLS),
    help='Asset da scaricare (default xau)')
parser.add_argument('--days', type=int, default=730, help='Giorni di storia (default 730)')
parser.add_argument('--tf',   type=str, default='H1',
    choices=['M5','M15','M30','H1','H4','D1'], help='Timeframe (default H1)')
parser.add_argument('--all-tf', action='store_true',
    help='Scarica tutti i TF (M5,M15,M30,H1,H4,D1) per l\'asset scelto — ignora --tf/--out')
parser.add_argument('--out',  type=str, default=None,
    help='File output (default data/{asset}_{tf}_mt5.json)')
args = parser.parse_args()

ASSET            = args.asset
SYMBOL_CANDIDATES = ASSET_SYMBOLS[ASSET]
FILE_PREFIX      = ASSET_FILE_PREFIX[ASSET]
DAYS             = args.days
TF_NAME          = args.tf.upper()
OUT_FILE         = args.out or f"data/{FILE_PREFIX}_{TF_NAME.lower()}_mt5.json"

TF_MAP = {
    'M5':  ('TIMEFRAME_M5',   5),
    'M15': ('TIMEFRAME_M15', 15),
    'M30': ('TIMEFRAME_M30', 30),
    'H1':  ('TIMEFRAME_H1',  60),
    'H4':  ('TIMEFRAME_H4',  240),
    'D1':  ('TIMEFRAME_D1',  1440),
}

# ── IMPORT MT5 ────────────────────────────────────────────────────────────────
try:
    import MetaTrader5 as mt5
except ImportError:
    print("ERRORE: MetaTrader5 non installato. Esegui: pip install MetaTrader5")
    sys.exit(1)

def connect():
    """Inizializza MT5 e autentica."""
    if not mt5.initialize():
        print(f"ERRORE: mt5.initialize() fallito — {mt5.last_error()}")
        print("Assicurati che MetaTrader 5 sia aperto.")
        sys.exit(1)

    ok = mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER)
    if not ok:
        err = mt5.last_error()
        print(f"ERRORE login: {err}")
        # Prova senza login (potrebbe già essere autenticato)
        info = mt5.account_info()
        if not info:
            mt5.shutdown()
            sys.exit(1)
        print(f"Già autenticato: account {info.login}")
    else:
        info = mt5.account_info()
        print(f"Connesso: {info.login} @ {info.server} | Saldo: {info.balance:.2f} {info.currency}")

def find_symbol():
    """Trova il simbolo GOLD attivo nel broker."""
    for sym in SYMBOL_CANDIDATES:
        info = mt5.symbol_info(sym)
        if info is not None and info.visible:
            print(f"Simbolo trovato: {sym} (digits={info.digits}, spread={info.spread})")
            return sym
        # prova ad attivare il simbolo
        if info is not None:
            mt5.symbol_select(sym, True)
            info = mt5.symbol_info(sym)
            if info and info.visible:
                print(f"Simbolo attivato: {sym}")
                return sym
    print("ERRORE: Nessun simbolo GOLD trovato. Verifica il broker.")
    mt5.shutdown()
    sys.exit(1)

def rates_to_candles(rates, cutoff):
    """Converte numpy structured array MT5 → lista dict, filtrando per cutoff."""
    candles = []
    for r in rates:
        if float(r['time']) < cutoff:
            continue
        o = float(r['open']);  h = float(r['high'])
        l = float(r['low']);   c = float(r['close'])
        try:
            v = float(r['tick_volume']) or float(r['real_volume'])
        except Exception:
            v = 0.0
        if math.isnan(c) or c <= 0:
            continue
        candles.append({'t': int(r['time']), 'o': o, 'h': h, 'l': l, 'c': c, 'v': v})
    return candles

def fetch_candles(symbol, days, tf_name=None):
    """Scarica candele per gli ultimi `days` giorni."""
    tf_name   = (tf_name or TF_NAME).upper()
    tf_attr   = getattr(mt5, TF_MAP[tf_name][0])
    tf_min    = TF_MAP[tf_name][1]
    date_to   = datetime.datetime.now(datetime.timezone.utc)
    date_from = date_to - datetime.timedelta(days=days + 5)  # +5 buffer weekend/festivi
    cutoff    = (date_to - datetime.timedelta(days=days)).timestamp()

    print(f"Scaricando {symbol} {tf_name} dal {date_from.strftime('%Y-%m-%d')} al {date_to.strftime('%Y-%m-%d')}...")

    rates = mt5.copy_rates_range(symbol, tf_attr, date_from, date_to)

    # Fallback per TF brevi (M5/M15): il terminal potrebbe non avere la storia
    # pre-caricata → chiediamo per count dal bar corrente.
    if rates is None or len(rates) == 0:
        bars_per_day = (24 * 60) / tf_min          # ~24h/day
        trading_days = days * (5 / 7)              # ~5 giorni/settimana
        max_bars     = min(int(trading_days * bars_per_day * 1.2), 99_999)
        print(f"  copy_rates_range vuoto ({mt5.last_error()}), provo copy_rates_from_pos ({max_bars} bar)...")
        rates = mt5.copy_rates_from_pos(symbol, tf_attr, 0, max_bars)

    if rates is None or len(rates) == 0:
        print(f"  ATTENZIONE: Nessuna candela {tf_name} ricevuta — {mt5.last_error()}")
        print("  Per M5/M15: apri il grafico in MT5 e scorri indietro per pre-caricare la storia.")
        return []

    return rates_to_candles(rates, cutoff)

def save(candles, path, symbol, tf_name):
    """Salva in formato compatibile con il backtester."""
    payload = {
        'candles': candles,
        'fetched_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'source': 'MT5',
        'symbol': symbol,
        'asset': ASSET,
        'timeframe': tf_name,
        'days': DAYS,
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f)
    print(f"Salvato: {path} ({len(candles)} candele)")

def run_one_tf(symbol, tf_name):
    tf_name  = tf_name.upper()
    out_file = args.out or f"data/{FILE_PREFIX}_{tf_name.lower()}_mt5.json"
    if args.all_tf:
        out_file = f"data/{FILE_PREFIX}_{tf_name.lower()}_mt5.json"  # --out ignorato in modalità all-tf
    candles = fetch_candles(symbol, DAYS, tf_name)
    if not candles:
        print(f"  [{tf_name}] nessuna candela valida — skip\n")
        return False
    prices = [c['c'] for c in candles]
    dates  = [datetime.datetime.fromtimestamp(c['t'], tz=datetime.timezone.utc) for c in candles]
    print(f"  [{tf_name}] {len(candles)} candele | {dates[0]:%Y-%m-%d} → {dates[-1]:%Y-%m-%d} | "
          f"min/max {min(prices):.2f}/{max(prices):.2f} | ultimo {prices[-1]:.2f}")
    save(candles, out_file, symbol, tf_name)
    return True

# ── MAIN ─────────────────────────────────────────────────────────────────────
connect()
SYMBOL = find_symbol()

tfs = ['M5','M15','M30','H1','H4','D1'] if args.all_tf else [TF_NAME]
print(f"\nAsset: {ASSET} | Simbolo: {SYMBOL} | TF: {', '.join(tfs)} | {DAYS} giorni\n")
ok = [run_one_tf(SYMBOL, tf) for tf in tfs]
mt5.shutdown()

if not any(ok):
    print("\nERRORE: nessun TF scaricato.")
    sys.exit(1)

print("\nDone. Usa i file con il backtester, es:")
print(f"  python scripts/strategy-engine-v2.py --file data/{FILE_PREFIX}_h1_mt5.json")
if not args.all_tf:
    print(f"\nPer scaricare tutti i TF di {ASSET}:")
    print(f"  python scripts/fetch_mt5_history.py --asset {ASSET} --all-tf")
