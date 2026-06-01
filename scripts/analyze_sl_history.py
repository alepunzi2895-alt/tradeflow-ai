"""
TradeFlow AI — Analisi Stop Loss dallo storico MT5
═══════════════════════════════════════════════════

Legge performance_cache.json (popolato da performance_tracker.py) e mostra:
  - SL rate per strategia
  - SL rate per regime
  - SL rate per ora UTC (heatmap testuale)
  - SL rate per sessione (Asian/London/NY)
  - Sequenze di SL consecutivi

Uso:
  python scripts/analyze_sl_history.py
  python scripts/analyze_sl_history.py --days 30
  python scripts/analyze_sl_history.py --strategy S16_GOLDEN_SQUEEZE
  python scripts/analyze_sl_history.py --mt5   # legge direttamente da MT5 (richiede MT5 aperto)
"""

import json
import os
import sys
import argparse
import datetime
from collections import defaultdict

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'performance_cache.json')
MAGIC = 20250413
SYMBOL = 'GOLD'

SESSION_HOURS = {
    'Asian':  range(0, 8),
    'London': range(8, 13),
    'NY':     range(13, 22),
    'Off':    range(22, 24),
}


def session_from_hour(h):
    for name, rng in SESSION_HOURS.items():
        if h in rng:
            return name
    return 'Off'


def load_from_cache(days=None, strategy_filter=None):
    if not os.path.exists(CACHE_FILE):
        print(f"[!] Cache non trovata: {CACHE_FILE}")
        print("    Avvia il bot con MT5 aperto per popolarla, oppure usa --mt5")
        return []
    with open(CACHE_FILE, encoding='utf-8') as f:
        data = json.load(f)
    trades = data if isinstance(data, list) else data.get('trades', [])
    if days:
        cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat()[:10]
        trades = [t for t in trades if t.get('exit_time', '')[:10] >= cutoff]
    if strategy_filter:
        trades = [t for t in trades if t.get('strategy_id') == strategy_filter]
    return trades


def load_from_mt5(days=30, strategy_filter=None):
    if not MT5_AVAILABLE:
        print("[!] MetaTrader5 non disponibile — installa: pip install MetaTrader5")
        return []
    if not mt5.initialize():
        print(f"[!] MT5 init fallito: {mt5.last_error()}")
        return []

    from_dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    deals = mt5.history_deals_get(from_dt, datetime.datetime.now(datetime.timezone.utc))
    mt5.shutdown()
    if deals is None:
        print(f"[!] history_deals_get fallito: {mt5.last_error()}")
        return []

    # Accoppia ENTRY + EXIT per position_id
    by_pos = defaultdict(list)
    for d in deals:
        if d.symbol != SYMBOL or d.magic != MAGIC:
            continue
        by_pos[d.position_id].append(d)

    trades = []
    for pos_id, pos_deals in by_pos.items():
        entry = next((d for d in pos_deals if d.entry == 0), None)
        exits = [d for d in pos_deals if d.entry == 1]
        if not entry or not exits:
            continue
        total_profit = sum(d.profit for d in exits)
        strategy_id = None
        comment = (entry.comment or '').strip()
        if comment.startswith('TF-AI '):
            strategy_id = comment[6:].strip()
        if strategy_filter and strategy_id != strategy_filter:
            continue
        exit_time = datetime.datetime.fromtimestamp(max(d.time for d in exits), tz=datetime.timezone.utc)
        entry_time = datetime.datetime.fromtimestamp(entry.time, tz=datetime.timezone.utc)
        trades.append({
            'strategy_id': strategy_id or 'UNKNOWN',
            'profit': round(total_profit, 2),
            'entry_time': entry_time.isoformat(),
            'exit_time': exit_time.isoformat(),
            'direction': 'buy' if entry.type == 0 else 'sell',
            'duration_min': int((exit_time - entry_time).total_seconds() / 60),
        })
    return trades


def analyze(trades):
    if not trades:
        print("Nessun trade trovato.")
        return

    total = len(trades)
    wins  = [t for t in trades if t['profit'] > 0]
    losses = [t for t in trades if t['profit'] <= 0]
    print(f"\n{'='*60}")
    print(f"ANALISI STOP LOSS — {total} trade totali")
    print(f"{'='*60}")
    print(f"  Win:  {len(wins)} ({100*len(wins)/total:.1f}%)   Avg P&L: ${sum(t['profit'] for t in wins)/max(len(wins),1):.2f}")
    print(f"  Loss: {len(losses)} ({100*len(losses)/total:.1f}%)  Avg P&L: ${sum(t['profit'] for t in losses)/max(len(losses),1):.2f}")
    pf = abs(sum(t['profit'] for t in wins)) / max(abs(sum(t['profit'] for t in losses)), 0.01)
    print(f"  PF:   {pf:.3f}  |  P&L totale: ${sum(t['profit'] for t in trades):.2f}")

    # ── Per strategia ──────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("SL RATE PER STRATEGIA")
    print(f"{'─'*60}")
    by_strat = defaultdict(list)
    for t in trades:
        by_strat[t['strategy_id']].append(t)
    for sid, strades in sorted(by_strat.items(), key=lambda x: -len(x[1])):
        sw = [t for t in strades if t['profit'] > 0]
        sl = [t for t in strades if t['profit'] <= 0]
        avg_sl = sum(t['profit'] for t in sl) / max(len(sl), 1)
        avg_tp = sum(t['profit'] for t in sw) / max(len(sw), 1)
        spf = abs(sum(t['profit'] for t in sw)) / max(abs(sum(t['profit'] for t in sl)), 0.01)
        print(f"  {sid:<28} | {len(strades):>4} trade | WR {100*len(sw)/len(strades):>5.1f}% | PF {spf:.2f} | SL avg ${avg_sl:.2f} | TP avg ${avg_tp:.2f}")

    # ── Per ora UTC ────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("SL RATE PER ORA UTC (SL% / n trade)")
    print(f"{'─'*60}")
    by_hour = defaultdict(list)
    for t in trades:
        h = int(t['exit_time'][11:13])
        by_hour[h].append(t)
    row = ""
    for h in range(24):
        ts = by_hour[h]
        if not ts:
            row += f"  {h:02d}h  —— "
        else:
            sl_pct = 100 * sum(1 for t in ts if t['profit'] <= 0) / len(ts)
            row += f"  {h:02d}h {sl_pct:4.0f}%/{len(ts)}"
        if (h + 1) % 6 == 0:
            print(row)
            row = ""

    # ── Per sessione ───────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("SL RATE PER SESSIONE")
    print(f"{'─'*60}")
    by_sess = defaultdict(list)
    for t in trades:
        h = int(t['exit_time'][11:13])
        by_sess[session_from_hour(h)].append(t)
    for sess in ['Asian', 'London', 'NY', 'Off']:
        ts = by_sess[sess]
        if not ts:
            continue
        sl_cnt = sum(1 for t in ts if t['profit'] <= 0)
        avg_dur = sum(t.get('duration_min', 0) for t in ts) / len(ts)
        print(f"  {sess:<8} | {len(ts):>4} trade | SL {sl_cnt:>3} ({100*sl_cnt/len(ts):>5.1f}%) | durata media {avg_dur:.0f}min")

    # ── Sequenze SL ────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("SEQUENZE SL CONSECUTIVI")
    print(f"{'─'*60}")
    sorted_trades = sorted(trades, key=lambda t: t['exit_time'])
    streak = 0; max_streak = 0; streaks = []
    for t in sorted_trades:
        if t['profit'] <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            if streak >= 2:
                streaks.append(streak)
            streak = 0
    if streak >= 2:
        streaks.append(streak)
    print(f"  Max streak SL:    {max_streak}")
    print(f"  Streak ≥2 trovate: {len(streaks)}")
    if streaks:
        print(f"  Distribuzione:    {dict(sorted({s: streaks.count(s) for s in set(streaks)}.items()))}")

    # ── Giorni con 2+ SL ───────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("GIORNI CON 2+ SL")
    print(f"{'─'*60}")
    by_day_sl = defaultdict(int)
    for t in trades:
        if t['profit'] <= 0:
            by_day_sl[t['exit_time'][:10]] += 1
    bad_days = {d: n for d, n in by_day_sl.items() if n >= 2}
    if bad_days:
        for d, n in sorted(bad_days.items()):
            day_trades = [t for t in trades if t['exit_time'][:10] == d]
            day_pnl = sum(t['profit'] for t in day_trades)
            print(f"  {d}  {n} SL  |  P&L giornaliero: ${day_pnl:.2f}")
    else:
        print("  Nessun giorno con 2+ SL nel periodo")

    print(f"\n{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description='Analisi Stop Loss TradeFlow AI')
    parser.add_argument('--days', type=int, default=90, help='Ultimi N giorni (default: 90)')
    parser.add_argument('--strategy', type=str, default=None, help='Filtra per strategia (es. S16_GOLDEN_SQUEEZE)')
    parser.add_argument('--mt5', action='store_true', help='Legge direttamente da MT5 (richiede MT5 aperto)')
    args = parser.parse_args()

    print(f"Caricamento trade (ultimi {args.days} giorni{'  — solo ' + args.strategy if args.strategy else ''})...")

    if args.mt5:
        trades = load_from_mt5(days=args.days, strategy_filter=args.strategy)
        print(f"Caricati {len(trades)} trade da MT5")
    else:
        trades = load_from_cache(days=args.days, strategy_filter=args.strategy)
        print(f"Caricati {len(trades)} trade da cache")

    analyze(trades)


if __name__ == '__main__':
    main()
