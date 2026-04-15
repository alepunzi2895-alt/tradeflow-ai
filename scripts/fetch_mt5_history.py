#!/usr/bin/env python3
"""
TradeFlow AI — Fetch storico H1 GOLD da MetaTrader 5
Salva i dati in xauusd_h1_mt5.json (stesso formato usato dal backtester).

USO:
  python scripts/fetch_mt5_history.py              # 730 giorni (default)
  python scripts/fetch_mt5_history.py --days 365   # 1 anno
  python scripts/fetch_mt5_history.py --out custom.json

PREREQUISITI:
  pip install MetaTrader5
  MT5 deve essere aperto con l'account configurato sotto.
"""

import sys, io, argparse, json, math, datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ── CONFIG (stessi valori di mt5-bot.py) ─────────────────────────────────────
MT5_LOGIN    = 1301224666
MT5_PASSWORD = "Alessandro95!"
MT5_SERVER   = "XMGlobal-MT5 6"

SYMBOL_CANDIDATES = ["GOLD", "XAUUSD", "XAUUSD.m", "XAUUSD_micro"]

# ── ARGPARSE ──────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description='Fetch storico GOLD da MT5 (multi-TF)')
parser.add_argument('--days', type=int, default=730, help='Giorni di storia (default 730)')
parser.add_argument('--tf',   type=str, default='H1',
    choices=['M5','M15','M30','H1','H4','D1'], help='Timeframe (default H1)')
parser.add_argument('--out',  type=str, default=None,
    help='File output (default xauusd_{tf}_mt5.json)')
args = parser.parse_args()

DAYS     = args.days
TF_NAME  = args.tf.upper()
OUT_FILE = args.out or f"xauusd_{TF_NAME.lower()}_mt5.json"

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

def fetch_candles(symbol, days):
    """Scarica candele per gli ultimi `days` giorni."""
    tf_attr   = getattr(mt5, TF_MAP[TF_NAME][0])
    tf_min    = TF_MAP[TF_NAME][1]
    date_to   = datetime.datetime.now(datetime.timezone.utc)
    date_from = date_to - datetime.timedelta(days=days + 5)  # +5 buffer weekend/festivi
    cutoff    = (date_to - datetime.timedelta(days=days)).timestamp()

    print(f"Scaricando {symbol} {TF_NAME} dal {date_from.strftime('%Y-%m-%d')} al {date_to.strftime('%Y-%m-%d')}...")

    rates = mt5.copy_rates_range(symbol, tf_attr, date_from, date_to)

    # Fallback per TF brevi (M5/M15): il terminal potrebbe non avere la storia
    # pre-caricata → chiediamo per count dal bar corrente.
    if rates is None or len(rates) == 0:
        bars_per_day = (24 * 60) / tf_min          # gold ~24h/day
        trading_days = days * (5 / 7)              # ~5 giorni/settimana
        max_bars     = min(int(trading_days * bars_per_day * 1.2), 99_999)
        print(f"  copy_rates_range vuoto ({mt5.last_error()}), provo copy_rates_from_pos ({max_bars} bar)...")
        rates = mt5.copy_rates_from_pos(symbol, tf_attr, 0, max_bars)

    if rates is None or len(rates) == 0:
        print(f"ERRORE: Nessuna candela ricevuta — {mt5.last_error()}")
        print("  Per M5/M15: apri il grafico in MT5 e scorri indietro per pre-caricare la storia.")
        mt5.shutdown()
        sys.exit(1)

    return rates_to_candles(rates, cutoff)

def save(candles, path):
    """Salva in formato compatibile con il backtester."""
    payload = {
        'candles': candles,
        'fetched_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'source': 'MT5',
        'symbol': SYMBOL,
        'timeframe': TF_NAME,
        'days': DAYS,
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f)
    print(f"Salvato: {path} ({len(candles)} candele)")

# ── MAIN ─────────────────────────────────────────────────────────────────────
connect()
SYMBOL = find_symbol()
candles = fetch_candles(SYMBOL, DAYS)

if not candles:
    print("ERRORE: Nessuna candela valida dopo il filtro.")
    mt5.shutdown()
    sys.exit(1)

# Statistiche rapide
prices = [c['c'] for c in candles]
dates  = [datetime.datetime.fromtimestamp(c['t'], tz=datetime.timezone.utc) for c in candles]
print(f"\nRisultato:")
print(f"  Candele totali : {len(candles)}")
print(f"  Periodo        : {dates[0].strftime('%Y-%m-%d')} → {dates[-1].strftime('%Y-%m-%d')}")
print(f"  Prezzo min/max : ${min(prices):.2f} / ${max(prices):.2f}")
print(f"  Ultimo prezzo  : ${prices[-1]:.2f}")

save(candles, OUT_FILE)
mt5.shutdown()
print("\nDone. Usa questo file con i backtester:")
print(f"  python scripts/strategy-engine-v2.py --file {OUT_FILE}")
print(f"  python scripts/backtest_obv_rsi_mom.py --{TF_NAME.lower()}-file {OUT_FILE}")
print()
print("Per scaricare tutti i TF:")
for tf in ['M15','M30','H1','H4','D1']:
    print(f"  python scripts/fetch_mt5_history.py --tf {tf}")
