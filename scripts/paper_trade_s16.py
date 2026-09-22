#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Paper trader S16_GOLDEN_SQUEEZE — 2026-09-22

Registra cosa FAREBBE S16 su H1 senza aprire ordini reali (bloccata dal 2026-09-17).
Non tocca mt5-bot.py né hard_blocks.json. Obiettivo: raccogliere evidenza FORWARD vera —
l'audit 2026-09-18 (backtests/results/audit_2026-09-18/S16_GOLDEN_SQUEEZE.json) mostra S16
solida su full/holdout/segmenti/cost-stress ma bocciata dal gate DSR (p-value ≈ 0, non
distinguibile dal rumore dati i 1753 trial cumulativi del programma di ricerca). Altro
backtest sugli stessi dati storici non risolve un fallimento DSR — lo peggiora (aumenta
num_trials). Solo trade forward su dati mai visti prima possono farlo. Vedi 07_self_learning_log.md
2026-09-22.

Fedeltà al backtest canonico (strategy-engine-v2.py::run_one(), stesso motore dell'audit):
  - segnale: signals.signal_golden_squeeze(ind, i, h1_trend=Supertrend H1, hour=hour) —
    NIENTE h4_trend esplicito: il backtester canonico non lo passa mai (fn(ind,i,h1_trend=...,
    hour=...) generico), quindi usa il proxy interno EMA200-in-salita — replicarlo esattamente,
    non il Supertrend H4 reale che usa invece mt5-bot.py in live (divergenza nota, vedi
    05_backtest.md "Divergenza bot ↔ backtester").
  - indicatori: strategy-engine-v2.py::compute_all() (stesso motore del backtest, non la
    pipeline separata di mt5-bot.py) — coerenza con i numeri dell'audit, non con mt5-bot.py.
  - TP/SL: 3.5×ATR / 2.0×ATR (STRATEGY_ATR_PARAMS/run_one, invariato dal 2026-04-30).
  - uscita: backtest_execution.simulate_exit() — stesso BE(80% risk)/trailing(1.2R trigger,
    0.7R distanza)/gap-through-stop del motore canonico, lookahead 30 barre H1.
  - entry: candles[i+1]['o'] (next-bar-open, come nel backtest) — se la barra i+1 non è ancora
    disponibile nel fetch corrente, il segnale non viene registrato ORA: la finestra di scan
    larga (ultime ~100 barre) + il dedup per bar_time lo cattura al prossimo giro, quando
    esisterà. Costi: stessa formula di trade_cost() in strategy-engine-v2.py.

Stato: data/s16_paper_trades.json

Uso:
  python -X utf8 scripts/paper_trade_s16.py            # un ciclo live: rileva + aggiorna + stampa
  python -X utf8 scripts/paper_trade_s16.py --summary  # solo riepilogo, nessuna nuova rilevazione
  python -X utf8 scripts/paper_trade_s16.py --replay   # rigioca l'intero storico locale (no MT5),
                                                        # stato separato in s16_paper_trades_replay.json —
                                                        # NON è nuova evidenza forward (stessi dati
                                                        # dell'audit, stesso motore): serve solo a
                                                        # verificare il meccanismo del tool su una serie
                                                        # lunga, i numeri aggregati combaciano con l'audit
                                                        # per costruzione, non aggiungono nulla al gate DSR.
"""
import sys, os, json, argparse, datetime, importlib.util
from dotenv import load_dotenv
load_dotenv()

_ap = argparse.ArgumentParser()
_ap.add_argument('--summary', action='store_true', help='solo riepilogo, nessuna nuova rilevazione')
_ap.add_argument('--replay', nargs='?', const=True, default=None,
                 help="rigioca uno storico locale invece di MT5 (default data/xauusd_h1_mt5.json)")
ARGS = _ap.parse_args()

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from backtest_execution import simulate_exit
from signals import signal_golden_squeeze

# Import se2 via importlib (filename con trattino) SOLO per compute_all() — load_from_file
# non viene mai chiamato, niente dati storici caricati solo per importare (stesso pattern di
# research_s20_fib_v2.py). sys.argv protetto: se2 fa il proprio argparse all'exec_module.
_spec = importlib.util.spec_from_file_location("se2", os.path.join(HERE, "strategy-engine-v2.py"))
se2 = importlib.util.module_from_spec(_spec)
_saved_argv = sys.argv
sys.argv = [sys.argv[0]]
_spec.loader.exec_module(se2)
sys.argv = _saved_argv

STATE_FILE = os.path.join(HERE, '..', 'data',
                           's16_paper_trades_replay.json' if ARGS.replay else 's16_paper_trades.json')
DEFAULT_REPLAY_FILE = os.path.join(HERE, '..', 'data', 'xauusd_h1_mt5.json')
TP_ATR_MULT = 3.5
SL_ATR_MULT = 2.0
LOOKAHEAD_BARS = 30            # barre H1, come run_one() per S16 (tf_mult=1 su H1)
SCAN_LOOKBACK = 260            # barre H1 riesaminate ad ogni giro (>> intervallo di run atteso)
WARMUP_BARS = 233              # signal_golden_squeeze richiede i>=233

MT5_LOGIN    = int(os.getenv("MT5_LOGIN", 1301224666))
MT5_PASSWORD = os.getenv("MT5_PASSWORD") or ""
if not MT5_PASSWORD and not ARGS.replay:
    raise RuntimeError("MT5_PASSWORD non impostata — aggiungila a .env prima di eseguire questo script.")
MT5_SERVER   = os.getenv("MT5_SERVER", "XMGlobal-MT5 6")
SYMBOL_CANDIDATES = ["GOLD", "XAUUSD", "XAUUSD.m"]


def _connect():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
            raise RuntimeError(f"mt5.initialize fallito: {mt5.last_error()}")
    for s in SYMBOL_CANDIDATES:
        if mt5.symbol_info(s) is not None:
            mt5.symbol_select(s, True)
            return mt5, s
    raise RuntimeError("Nessun simbolo GOLD/XAUUSD trovato in MT5")


def _fetch_h1(mt5, symbol, n=WARMUP_BARS + SCAN_LOOKBACK + LOOKAHEAD_BARS + 50):
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 1, n)  # start_pos=1 → solo barre chiuse
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"nessuna candela H1: {mt5.last_error()}")
    out = []
    for r in rates:
        c = float(r['close'])
        if c <= 0:
            continue
        try:
            vol = float(r['tick_volume']) or float(r['real_volume'])
        except Exception:
            vol = 0.0
        out.append({'t': int(r['time']), 'o': float(r['open']), 'h': float(r['high']),
                    'l': float(r['low']), 'c': c, 'v': vol})
    return out


def _trade_cost(is_stop):
    """Stessa formula di strategy-engine-v2.py::trade_cost() (COSTS_ON default)."""
    HALF_SPREAD_USD, SLIP_ENTRY_USD, SLIP_SL_USD, COMMISSION_USD = 0.15, 0.05, 0.10, 0.0
    c = 2 * HALF_SPREAD_USD + SLIP_ENTRY_USD + COMMISSION_USD
    if is_stop:
        c += SLIP_SL_USD
    return c


def _load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding='utf-8') as f:
            return json.load(f)
    return {'strategy': 'S16_GOLDEN_SQUEEZE', 'started': None, 'signals': []}


def _save_state(st):
    st['updated'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(st, f, indent=2)


def _dir_stats(closed):
    if not closed:
        return None
    n = len(closed); wins = [s for s in closed if s['pnl'] > 0]
    gw = sum(s['pnl'] for s in wins)
    gl = abs(sum(s['pnl'] for s in closed if s['pnl'] <= 0))
    pf = round(gw / gl, 3) if gl > 0 else (float('inf') if gw > 0 else 0.0)
    return {'n': n, 'wr': round(100 * len(wins) / n, 1), 'pf': pf,
            'pnl': round(sum(s['pnl'] for s in closed), 2)}


def _stats_line(sigs):
    d = _dir_stats([s for s in sigs if s['status'] == 'closed'])
    if not d:
        return "  nessun trade chiuso ancora"
    return f"  chiusi={d['n']}  WR={d['wr']:.0f}%  PF={d['pf']:.2f}  P&L=${d['pnl']:+.1f}"


def main():
    a = ARGS
    st = _load_state()
    symbol = None
    if a.replay:
        path = a.replay if isinstance(a.replay, str) else DEFAULT_REPLAY_FILE
        candles, _ = se2.load_from_file(path)
        symbol = f"replay:{os.path.basename(path)}"
    else:
        mt5, symbol = _connect()
        try:
            candles = _fetch_h1(mt5, symbol)
        finally:
            mt5.shutdown()

    ind = se2.compute_all(candles)
    n = len(candles)
    known = {s['bar_time'] for s in st['signals']}
    new_sigs = 0

    if not a.summary:
        # Live: solo le ultime SCAN_LOOKBACK barre (-2 così i+1, il next-bar-open, è sempre
        # disponibile; l'ultima barra del fetch non viene mai processata ORA, la cattura il
        # giro successivo — stesso motivo di scan largo di paper_trade_s20.py). Replay: l'intero
        # file, i+1 sempre disponibile tranne l'ultimissima barra.
        scan_start = WARMUP_BARS if a.replay else max(WARMUP_BARS, n - SCAN_LOOKBACK)
        for i in range(scan_start, n - 1):
            bt = candles[i]['t']
            if bt in known:
                continue
            dt = datetime.datetime.fromtimestamp(bt, tz=datetime.timezone.utc)
            h1t = ind['st'][i] if ind.get('st') else None
            sig = signal_golden_squeeze(ind, i, h1_trend=h1t, hour=dt.hour)  # niente h4_trend: vedi docstring
            if sig is None:
                continue
            av = ind['atr'][i]
            if not av:
                continue
            curr_tp = round(av * TP_ATR_MULT, 2)
            curr_sl = round(av * SL_ATR_MULT, 2)
            entry = candles[i + 1]['o']
            tp_p = entry + curr_tp if sig == 'buy' else entry - curr_tp
            sl_p = entry - curr_sl if sig == 'buy' else entry + curr_sl
            st['signals'].append({
                'bar_time': bt,
                'bar_utc': dt.isoformat(),
                'detected_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'entry_bar_time': candles[i + 1]['t'],
                'dir': sig, 'entry': round(entry, 2), 'sl': round(sl_p, 2), 'tp': round(tp_p, 2),
                'status': 'open', 'pnl': None, 'resolution': None, 'closed_utc': None,
            })
            known.add(bt); new_sigs += 1
        if st['started'] is None and st['signals']:
            st['started'] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Aggiorna gli aperti: simulate_exit() è lo stesso motore causale del backtest canonico.
    # Se il lookahead di 30 barre eccede i dati oggi disponibili, un esito 'time' a quel
    # confine NON è una vera chiusura — è solo "non ancora abbastanza barre live" — resta
    # aperta e si ricontrolla al prossimo giro, senza chiuderla in anticipo per errore.
    tmap = {c['t']: k for k, c in enumerate(candles)}
    resolved = 0
    for s in st['signals']:
        if s['status'] != 'open':
            continue
        entry_idx = tmap.get(s['entry_bar_time'])
        if entry_idx is None:
            continue  # barra entry fuori dalla finestra fetchata (troppo vecchia o non ancora nota)
        lookahead_end = entry_idx + LOOKAHEAD_BARS
        fetch_end = min(lookahead_end, n)
        fill = simulate_exit(candles, entry_idx, fetch_end, s['entry'], s['sl'], s['tp'], s['dir'] == 'buy')
        if fill is None:
            continue
        hit_true_boundary = fetch_end >= lookahead_end or fill['reason'] != 'time'
        if fill['reason'] == 'time' and not hit_true_boundary:
            continue  # dati insufficienti per concludere, non una vera time-exit — resta open
        pnl = (fill['price'] - s['entry']) if s['dir'] == 'buy' else (s['entry'] - fill['price'])
        pnl -= _trade_cost(fill['reason'] == 'sl')
        s['status'] = 'closed'; s['pnl'] = round(pnl, 2); s['resolution'] = fill['reason']
        s['closed_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        resolved += 1

    if not a.summary:
        _save_state(st)

    opens = [s for s in st['signals'] if s['status'] == 'open']
    print(f"S16 paper — {symbol} H1 · {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')}Z")
    print(f"  nuovi segnali: {new_sigs}   risolti ora: {resolved}   aperti: {len(opens)}   totali: {len(st['signals'])}")
    print(_stats_line(st['signals']))
    for s in opens:
        print(f"  OPEN  {s['bar_utc'][:16]}  {s['dir'].upper():4} entry={s['entry']} sl={s['sl']} tp={s['tp']}")
    for s in sorted([x for x in st['signals'] if x['status'] == 'closed'], key=lambda x: x['bar_time'])[-5:]:
        print(f"  done  {s['bar_utc'][:16]}  {s['dir'].upper():4} {s['resolution']:5} pnl=${s['pnl']:+.1f}")


if __name__ == '__main__':
    main()
