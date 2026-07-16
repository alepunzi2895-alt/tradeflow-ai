"""
TradeFlow AI — Performance Tracker (Self-Learning Agent)
═══════════════════════════════════════════════════════════════════
Legge lo storico deals MT5, raggruppa i trade per strategia (dal campo
comment), calcola WR/PF rolling e alimenta il StrategySelector con
recent_wr_map per aggiustamenti dinamici del punteggio.

Quando una strategia sotto/sovraperforma il baseline del backtest, scrive
score_mult in data/strategy_overrides.json (letto da strategy_selector.py)
e appende una riga in directives/07_self_learning_log.md.

USAGE (da mt5-bot.py):
    from performance_tracker import get_performance_tracker
    tracker = get_performance_tracker(MAGIC)
    # ogni barra H1:
    tracker.update_from_mt5(mt5)
    changes = tracker.auto_apply_adjustments()
    recent_wr_map = tracker.get_recent_wr_map()
    selector.select(I, i, hour, recent_wr_map=recent_wr_map)
"""
import json
import os
import datetime
import logging
from collections import defaultdict

log = logging.getLogger('tf-bot')

# ── Baseline backtest (fonte: directives/02_strategies.md) ───────────────────
# WR adattivo per TF ottimale — backtest 2026-04-30 V2 (segnali ottimizzati)
BACKTEST_BASELINES = {
    "S00_MFKK":              {"wr": 0.494, "pf": 1.44},   # M30 adattivo 49.4% · 518 trade (V6)
    "S18_RANGE_REVERSAL":    {"wr": 0.450, "pf": 1.35},   # M30 stimato V1 (nessun backtest reale ancora)
    "S05_MFKK_INTRADAY":     {"wr": 0.253, "pf": 1.10},   # H1 adattivo 25.3% · 162 trade
    "S09_MFKK_SCALPING":     {"wr": 0.360, "pf": 1.40},   # H1 adattivo 36.0% · 25 trade
    "S10_OB_FVG_SCALP":      {"wr": 0.281, "pf": 1.28},   # H1 fresh backtest 2026-06-01: WR 0% su 4 trade live (aggiornato da 52.8%)
    "S16_GOLDEN_SQUEEZE":    {"wr": 0.514, "pf": 1.50},   # H1 adattivo 51.4% · 140 trade
    "S17_CONVERGENCE_SCALP": {"wr": 0.340, "pf": 1.75},   # H4 adattivo 34.0% · 103 trade
}

ROLLING_WINDOW      = 30    # trade recenti per WR/PF rolling
MIN_TRADES_ADJUST   = 8     # soglia minima per applicare aggiustamenti (abbassata da 10 per reattività)
BOOST_THRESHOLD     = 1.25  # WR recente > baseline × 1.25 → boost
PENALTY_THRESHOLD   = 0.70  # WR recente < baseline × 0.70 → penalty
HARD_BLOCK_WR_RATIO = 0.40  # WR recente < baseline × 0.40 → blocco completo (score_mult=0.0)
STREAK_PENALTY_N    = 4     # perdite consecutive → penalty temporanea (abbassato da 6)
MAX_CACHE_TRADES    = 500   # massimo trade in cache locale

COMMENT_PREFIX = "TF-AI "  # prefisso commento ordini (vedi place_order in mt5-bot.py)

_BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR      = os.path.join(_BASE_DIR, '..', 'data')
CACHE_PATH     = os.path.join(_DATA_DIR, 'performance_cache.json')
OVERRIDES_PATH = os.path.join(_DATA_DIR, 'strategy_overrides.json')
LOG_PATH       = os.path.join(_BASE_DIR, '..', 'directives', '07_self_learning_log.md')


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_strategy_from_comment(comment: str):
    """
    Estrae strategy_id dal commento ordine: 'TF-AI S16_GOLDEN_SQUEEZE' → 'S16_GOLDEN_SQUEEZE'.

    Il broker tronca il campo comment lato server (osservato 2026-07-09 sui dati
    live: 'TF-AI S16_GOLDEN' invece di 'TF-AI S16_GOLDEN_SQUEEZE', 'TF-AI S18_RANGE_'
    invece di 'TF-AI S18_RANGE_REVERSAL', ecc. — mt5-bot.py invia il comment completo,
    la troncatura avviene sul lato server/broker). Un match esatto contro
    BACKTEST_BASELINES scartava quindi in silenzio ogni trade di ogni strategia con
    nome >~10 caratteri — S00_MFKK (8 char) era l'unica a sopravvivere, l'unica
    tracciata dal self-learning. Fix: risolvi per prefisso contro gli strategy_id
    noti quando il match esatto fallisce; None (scarta) se ambiguo, mai un
    'quasi-match' che rischi di attribuire un trade alla strategia sbagliata.
    """
    if not comment:
        return None
    comment = comment.strip()
    if not comment.startswith(COMMENT_PREFIX):
        return None
    raw_sid = comment[len(COMMENT_PREFIX):].strip()
    if not raw_sid:
        return None
    if raw_sid in BACKTEST_BASELINES:
        return raw_sid
    matches = [sid for sid in BACKTEST_BASELINES if sid.startswith(raw_sid)]
    if len(matches) == 1:
        return matches[0]
    return None


# ── PerformanceTracker ────────────────────────────────────────────────────────

class PerformanceTracker:
    """
    Aggrega lo storico MT5 per strategia, calcola WR/PF rolling e
    genera aggiustamenti automatici del punteggio per il StrategySelector.
    """

    def __init__(self, magic: int = 20250413):
        self.magic      = magic
        self._cache     = self._load_cache()
        self._overrides = self._load_overrides()

    # ── I/O ───────────────────────────────────────────────────────────────────

    def _load_cache(self) -> dict:
        try:
            with open(CACHE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"trades": [], "last_update": None}

    def _save_cache(self):
        os.makedirs(_DATA_DIR, exist_ok=True)
        with open(CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(self._cache, f, indent=2, default=str)

    def _load_overrides(self) -> dict:
        try:
            with open(OVERRIDES_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_overrides(self):
        os.makedirs(_DATA_DIR, exist_ok=True)
        with open(OVERRIDES_PATH, 'w', encoding='utf-8') as f:
            json.dump(self._overrides, f, indent=2)

    # ── MT5 History ───────────────────────────────────────────────────────────

    def update_from_mt5(self, mt5, days_back: int = 90) -> int:
        """
        Legge deals MT5, accoppia entry+exit per position_id, aggiorna cache.
        Ritorna il numero di nuovi trade aggiunti.
        """
        from_dt = datetime.datetime.utcnow() - datetime.timedelta(days=days_back)
        to_dt   = datetime.datetime.utcnow() + datetime.timedelta(hours=1)

        try:
            deals = mt5.history_deals_get(from_dt, to_dt)
        except Exception as e:
            log.warning(f"[PerfTracker] history_deals_get error: {e}")
            return 0

        if deals is None or len(deals) == 0:
            return 0

        existing_ids = {t['pos_id'] for t in self._cache.get('trades', [])}
        new_trades   = []

        by_pos = defaultdict(list)
        for d in deals:
            if d.magic == self.magic:
                by_pos[d.position_id].append(d)

        for pos_id, pos_deals in by_pos.items():
            if pos_id in existing_ids:
                continue

            pos_deals.sort(key=lambda d: d.time)
            entries = [d for d in pos_deals if d.entry == 0]
            exits   = [d for d in pos_deals if d.entry == 1]

            if not entries or not exits:
                continue

            entry = entries[0]
            sid   = _parse_strategy_from_comment(entry.comment)
            if not sid:
                continue

            total_profit = sum(d.profit for d in exits)
            entry_dt  = datetime.datetime.utcfromtimestamp(entry.time).isoformat()
            exit_dt   = datetime.datetime.utcfromtimestamp(exits[-1].time).isoformat()

            new_trades.append({
                "pos_id":      pos_id,
                "strategy_id": sid,
                "direction":   "buy" if entry.type == 0 else "sell",
                "entry_price": entry.price,
                "profit":      round(total_profit, 2),
                "volume":      entry.volume,
                "time_open":   entry_dt,
                "time_close":  exit_dt,
                "win":         total_profit > 0,
            })

        if new_trades:
            self._cache.setdefault('trades', []).extend(new_trades)
            self._cache['trades'] = self._cache['trades'][-MAX_CACHE_TRADES:]
            self._cache['last_update'] = datetime.datetime.utcnow().isoformat()
            self._save_cache()
            log.info(
                f"[PerfTracker] +{len(new_trades)} nuovi trade "
                f"(cache tot={len(self._cache['trades'])})"
            )

        return len(new_trades)

    # ── Stats ─────────────────────────────────────────────────────────────────

    def get_strategy_stats(self, window: int = ROLLING_WINDOW) -> dict:
        """
        Calcola per ogni strategia (sugli ultimi `window` trade):
        n, wr, pf, total_profit, avg_profit, streak, streak_type.
        """
        by_strategy = defaultdict(list)
        for t in self._cache.get('trades', []):
            by_strategy[t['strategy_id']].append(t)

        stats = {}
        for sid, trades in by_strategy.items():
            recent  = trades[-window:]
            wins    = [t for t in recent if t['win']]
            losses  = [t for t in recent if not t['win']]
            gross_p = sum(t['profit'] for t in wins)
            gross_l = abs(sum(t['profit'] for t in losses)) or 1e-9
            total_p = sum(t['profit'] for t in recent)

            # Streak corrente (iterazione inversa)
            streak = 0
            streak_type = None
            for t in reversed(recent):
                kind = 'win' if t['win'] else 'loss'
                if streak_type is None:
                    streak_type = kind
                    streak = 1
                elif kind == streak_type:
                    streak += 1
                else:
                    break

            stats[sid] = {
                "n":            len(recent),
                "wr":           round(len(wins) / len(recent), 4) if recent else 0.0,
                "pf":           round(gross_p / gross_l, 3),
                "total_profit": round(total_p, 2),
                "avg_profit":   round(total_p / len(recent), 2) if recent else 0.0,
                "streak":       streak,
                "streak_type":  streak_type,
                "baseline_wr":  BACKTEST_BASELINES.get(sid, {}).get("wr", 0.35),
                "baseline_pf":  BACKTEST_BASELINES.get(sid, {}).get("pf", 1.0),
            }
        return stats

    def get_recent_wr_map(self, window: int = ROLLING_WINDOW) -> dict:
        """
        Ritorna {strategy_id: recent_wr} — passato a StrategySelector.select().
        Solo strategie con ≥ 5 trade recenti.
        """
        stats = self.get_strategy_stats(window)
        return {sid: s["wr"] for sid, s in stats.items() if s["n"] >= 5}

    # ── Self-Learning ─────────────────────────────────────────────────────────

    def suggest_adjustments(self) -> list:
        """
        Confronta WR recente vs baseline e suggerisce score_mult.
        Regole (priorità decrescente):
          • WR recente < 40% base   → 0.00 (hard_block — rimossa dalla rotation)
          • streak loss ≥ 4         → 0.50 (streak_penalty)
          • WR recente < 70% base   → 0.70 (underperform)
          • WR recente > 125% base  → 1.30 (outperform)
          • altrimenti              → 1.00 (normal)
        Richiede ≥ MIN_TRADES_ADJUST trade per attivarsi.
        """
        stats       = self.get_strategy_stats()
        suggestions = []

        for sid, s in stats.items():
            if s["n"] < MIN_TRADES_ADJUST:
                continue

            base_wr    = s["baseline_wr"]
            recent_wr  = s["wr"]
            ratio      = recent_wr / base_wr if base_wr > 0 else 1.0

            if ratio < HARD_BLOCK_WR_RATIO:
                # WR crolla sotto il 40% del baseline → blocco completo
                suggestions.append({
                    "strategy_id": sid,
                    "type":        "hard_block",
                    "reason":      f"WR {recent_wr:.1%} vs baseline {base_wr:.1%} ({ratio:.0%}) — BLOCCATA",
                    "score_mult":  0.0,
                })
            elif s["streak_type"] == "loss" and s["streak"] >= STREAK_PENALTY_N:
                suggestions.append({
                    "strategy_id": sid,
                    "type":        "streak_penalty",
                    "reason":      f"{s['streak']} perdite consecutive | WR={recent_wr:.1%}",
                    "score_mult":  0.50,
                })
            elif ratio < PENALTY_THRESHOLD:
                suggestions.append({
                    "strategy_id": sid,
                    "type":        "underperform",
                    "reason":      f"WR {recent_wr:.1%} vs baseline {base_wr:.1%} ({ratio:.0%})",
                    "score_mult":  0.70,
                })
            elif ratio > BOOST_THRESHOLD:
                suggestions.append({
                    "strategy_id": sid,
                    "type":        "outperform",
                    "reason":      f"WR {recent_wr:.1%} vs baseline {base_wr:.1%} ({ratio:.0%})",
                    "score_mult":  1.30,
                })
            else:
                suggestions.append({
                    "strategy_id": sid,
                    "type":        "normal",
                    "reason":      f"WR {recent_wr:.1%} in range ({ratio:.0%} vs baseline)",
                    "score_mult":  1.00,
                })

        return suggestions

    def auto_apply_adjustments(self) -> list:
        """
        Applica suggerimenti → strategy_overrides.json.
        Ritorna lista dei cambiamenti significativi (|Δmult| ≥ 0.15).
        """
        suggestions   = self.suggest_adjustments()
        new_overrides = {}
        changes       = []

        for s in suggestions:
            sid   = s["strategy_id"]
            mult  = s["score_mult"]
            prev  = self._overrides.get(sid, {}).get("score_mult", 1.0)

            new_overrides[sid] = {
                "score_mult": mult,
                "type":       s["type"],
                "reason":     s["reason"],
                "updated_at": datetime.datetime.utcnow().isoformat(),
            }

            if abs(mult - prev) >= 0.15:
                changes.append({
                    "strategy_id": sid,
                    "prev_mult":   prev,
                    "new_mult":    mult,
                    "type":        s["type"],
                    "reason":      s["reason"],
                })

        self._overrides = new_overrides
        self._save_overrides()

        if changes:
            self._log_changes_to_directive(changes)
            for c in changes:
                arrow = "⬇" if c["new_mult"] < 1.0 else "⬆"
                log.info(
                    f"[PerfTracker] {arrow} {c['strategy_id']} "
                    f"score_mult {c['prev_mult']:.2f}→{c['new_mult']:.2f} | {c['reason']}"
                )

        return changes

    def _log_changes_to_directive(self, changes: list):
        """Appende righe di cambiamento significativo in 07_self_learning_log.md."""
        try:
            today = datetime.date.today().isoformat()
            rows  = []
            for c in changes:
                arrow = "⬇️" if c["new_mult"] < 1.0 else "⬆️"
                rows.append(
                    f"| {today} | PerfTracker {c['strategy_id']}: "
                    f"score_mult {c['prev_mult']:.2f}→{c['new_mult']:.2f} {arrow} "
                    f"| {c['type']} | {c['reason']} |"
                )

            with open(LOG_PATH, 'r', encoding='utf-8') as f:
                content = f.read()

            marker = '|---|---|---|---|'
            insert = marker + '\n' + '\n'.join(rows)
            content = content.replace(marker, insert, 1)

            with open(LOG_PATH, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            log.warning(f"[PerfTracker] _log_changes error: {e}")

    # ── Report ────────────────────────────────────────────────────────────────

    def get_performance_report(self) -> str:
        """Testo riepilogativo per il log del bot (ogni ~6 ore)."""
        stats = self.get_strategy_stats()
        if not stats:
            return "[PerfTracker] Nessun trade in cache."

        lines = [f"── Performance Tracker — {datetime.date.today()} ──"]
        for sid in sorted(stats):
            s      = stats[sid]
            mult   = self._overrides.get(sid, {}).get("score_mult", 1.0)
            streak = (f" | streak {s['streak']}×{s['streak_type']}"
                      if s['streak_type'] else "")
            m_str  = f" [mult={mult:.2f}]" if mult != 1.0 else ""
            lines.append(
                f"  {sid:<26} n={s['n']:>3} | WR={s['wr']:.1%}"
                f" (base={s['baseline_wr']:.1%}) | PF={s['pf']:.3f}"
                f" | P&L={s['total_profit']:+.1f}{streak}{m_str}"
            )
        return '\n'.join(lines)

    def get_overrides(self) -> dict:
        """Ritorna {strategy_id: score_mult} per uso esterno."""
        return {sid: v["score_mult"] for sid, v in self._overrides.items()}


# ── Singleton ─────────────────────────────────────────────────────────────────
_instance: PerformanceTracker = None


def get_performance_tracker(magic: int = 20250413) -> PerformanceTracker:
    global _instance
    if _instance is None:
        _instance = PerformanceTracker(magic)
    return _instance
