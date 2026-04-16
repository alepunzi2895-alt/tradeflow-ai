"""
TradeFlow AI — Risk Manager Module
════════════════════════════════════════════════════════════════════
Gestione rischio adattiva basata sull'AI Score del tab Dashboard.

LOGICA PRINCIPALE:
  AI Score 0-100    # (max_score, lot_mult, tp_mult, sl_mult, be_trigger_pct, ts_step_atr_mult, partial_close)
    TIERS = [
        (40,  0.5, 1.0, 0.8, 0.80, 1.5, False, 'CONSERVATIVE'), # 🔵 Basso rischio
        (60,  0.8, 1.0, 1.0, 0.70, 1.5, False, 'NORMAL'),       # ⚪ Normale
        (75,  1.0, 1.5, 1.0, 0.60, 1.2, False, 'AGGRESSIVE'),   # 🟡 Conferme multiple
        (85,  1.2, 1.8, 1.2, 0.50, 1.0, False, 'STRONG'),       # 🟠 Setup istituzionale
        (100, 1.5, 2.0, 1.5, 0.50, 1.0, False, 'MAX'),          # 🔴 Massima confluenza
    ]

PARZIALIZZAZIONI:
  Al raggiungimento del 50% del TP → chiudi il 50% del lotto e sposta SL a BE
  Se score > 75 → lascia correre il restante 50% con trailing stop

TRAILING STOP:
  Attivato appena l'ordine supera il livello BE
  Step = 0.5 × ATR (aggiornato ad ogni barra)

USO:
  from risk_manager import RiskManager
  rm = RiskManager(base_lot=0.02, max_lot=0.10)
  params = rm.get_order_params(ai_score=78, atr=12.5, strategy='S00_MFKK')
  rm.manage_positions(positions, current_price, atr=12.5)
════════════════════════════════════════════════════════════════════
"""
import math
import logging

log = logging.getLogger('tf-bot')

# ── CONFIGURAZIONE TIER ────────────────────────────────────────────────────────
TIERS = [
    {'score_max': 40,  'lot_mult': 0.4, 'tp_mult': 1.0, 'sl_mult': 0.8, 'be_pct': 0.60, 'ts_step': 1.5, 'partial': True, 'partial_pct': 0.5, 'label': '🔵 CONSERVATIVE'},
    {'score_max': 60,  'lot_mult': 0.6, 'tp_mult': 1.0, 'sl_mult': 1.0, 'be_pct': 0.50, 'ts_step': 1.5, 'partial': True, 'partial_pct': 0.5, 'label': '⚪ NORMAL'},
    {'score_max': 75,  'lot_mult': 0.8, 'tp_mult': 1.5, 'sl_mult': 1.0, 'be_pct': 0.40, 'ts_step': 1.2, 'partial': True, 'partial_pct': 0.5, 'label': '🟡 AGGRESSIVE'},
    {'score_max': 85,  'lot_mult': 1.0, 'tp_mult': 1.8, 'sl_mult': 1.2, 'be_pct': 0.40, 'ts_step': 1.0, 'partial': True, 'partial_pct': 0.5, 'label': '🟠 STRONG'},
    {'score_max': 100, 'lot_mult': 1.2, 'tp_mult': 2.0, 'sl_mult': 1.5, 'be_pct': 0.35, 'ts_step': 1.0, 'partial': True, 'partial_pct': 0.5, 'label': '🔴 MAX'},
]

# TP/SL base in dollari per strategia (fallback se ATR non disponibile)
STRATEGY_BASE = {
    'S00_MFKK':            {'base_tp': 15.0, 'base_sl': 8.0,  'use_atr': False},
    'S05_MFKK_INTRADAY':   {'base_tp': None, 'base_sl': None,  'use_atr': True},
    'S09_MFKK_SCALPING':   {'base_tp': None, 'base_sl': None,  'use_atr': True},
    'S05_V3_Sell_Exhaust': {'base_tp': None, 'base_sl': None,  'use_atr': True},
    'S01_EXHAUSTION':      {'base_tp': None, 'base_sl': None,  'use_atr': True},
    'S13_STRUC_BREAK':     {'base_tp': None, 'base_sl': None,  'use_atr': True},
    'S15_OBV_MACD':       {'base_tp': None, 'base_sl': None,  'use_atr': True},
    'S04_BB_SQUEEZE':     {'base_tp': 15.0, 'base_sl': 10.0,  'use_atr': False},
    'S07_STOCHRSI_BB':    {'base_tp': 12.0, 'base_sl': 15.0,  'use_atr': False},
    'S11_ALLIGATOR_AWAKEN': {'base_tp': None, 'base_sl': None, 'use_atr': True},
}
ATR_TP_MULT_BASE = 1.5   # moltiplicatore ATR per TP base (ottimizzato su H1)
ATR_SL_MULT_BASE = 1.0   # moltiplicatore ATR per SL base (ottimizzato su H1)


class RiskManager:
    """
    Gestione rischio adattiva basata su AI Score.
    Integra lot sizing, TP/SL dinamici, BE, trailing stop e parzializzazioni.
    """

    def __init__(self, base_lot: float = 0.02, max_lot: float = 0.10,
                 lot_step: float = 0.01):
        self.base_lot  = base_lot    # lot size con score neutro (50)
        self.max_lot   = max_lot     # cap assoluto
        self.lot_step  = lot_step    # step minimo broker
        # traccia stato posizioni per BE/TS/partial
        self._pos_state: dict = {}   # {ticket: {'be_done': bool, 'partial_done': bool, 'ts_price': float}}

    # ── TIER DETECTION ─────────────────────────────────────────────────────────
    def get_tier(self, ai_score: float) -> dict:
        """Restituisce il tier di rischio corrispondente all'AI Score."""
        for tier in TIERS:
            if ai_score <= tier['score_max']:
                return tier
        return TIERS[-1]

    # ── ORDER PARAMS ────────────────────────────────────────────────────────────
    def get_order_params(self, ai_score: float, atr: float, strategy: str,
                         direction: str = 'buy') -> dict:
        """
        Calcola i parametri completi per un nuovo ordine:
        - lot_size   : lotto adattivo
        - tp_usd     : take profit in dollari
        - sl_usd     : stop loss in dollari
        - tp2_usd    : secondo TP per parzializzazione (se attiva)
        - be_trigger : prezzo di trigger per Break Even
        - ts_step    : step trailing stop in dollari
        - tier        : tier di rischio usato
        """
        tier = self.get_tier(ai_score)
        sb   = STRATEGY_BASE.get(strategy, {'base_tp': 20.0, 'base_sl': 12.0, 'use_atr': False})

        # ── Calcola TP/SL base ────────────────────────────────────────────
        if sb['use_atr'] and atr:
            base_tp = atr * ATR_TP_MULT_BASE
            base_sl = atr * ATR_SL_MULT_BASE
        else:
            base_tp = sb['base_tp'] or (atr * ATR_TP_MULT_BASE if atr else 20.0)
            base_sl = sb['base_sl'] or (atr * ATR_SL_MULT_BASE if atr else 12.0)

        # ── Applica moltiplicatori tier ───────────────────────────────────
        tp_usd = round(base_tp * tier['tp_mult'], 2)
        sl_usd = round(base_sl * tier['sl_mult'], 2)

        # ── Lot size ──────────────────────────────────────────────────────
        raw_lot = self.base_lot * tier['lot_mult']
        lot = self._round_lot(raw_lot)

        # ── Trailing stop step ────────────────────────────────────────────
        ts_step = round(atr * tier['ts_step'], 2) if atr else round(sl_usd * 0.3, 2)

        # ── Parzializzazione ──────────────────────────────────────────────
        partial_lot = None
        tp2_usd     = None
        if tier.get('partial'):
            partial_pct = tier.get('partial_pct', 0.5)
            partial_lot = self._round_lot(lot * partial_pct)
            # TP parziale = 50% del TP completo
            tp2_usd = round(tp_usd * 0.5, 2)

        # ── BE trigger (in dollari dal prezzo di entrata) ─────────────────
        be_trigger = round(tp_usd * tier['be_pct'], 2)

        result = {
            'lot':         lot,
            'tp_usd':      tp_usd,
            'sl_usd':      sl_usd,
            'be_trigger':  be_trigger,
            'ts_step':     ts_step,
            'partial':     tier.get('partial', False),
            'partial_lot': partial_lot,
            'tp2_usd':     tp2_usd,
            'tier':        tier['label'],
            'tier_label':  tier['label'],
            'ai_score':    round(ai_score, 1),
            'be_mult':     sb.get('be_mult'), # Passa il moltiplicatore BE
        }

        log.info(
            f"📊 RiskManager [{tier['label']}] score={ai_score:.0f} | "
            f"lot={lot} | TP=${tp_usd} | SL=${sl_usd} | "
            f"BE@+${be_trigger} | TS step=${ts_step}"
            + (f" | Partial {int(partial_pct*100)}% @TP${tp2_usd}" if tier.get('partial') else "")
        )
        return result

    # ── MANAGE POSITIONS (chiamato ad ogni tick nel loop del bot) ──────────────
    def manage_positions(self, mt5_module, symbol: str, magic: int,
                         current_atr: float) -> list:
        """
        Gestisce tutte le posizioni aperte:
        1. Parzializzazione: chiude 50% al raggungimento di TP2
        2. Break Even: sposta SL a entrata quando prezzo supera BE trigger
        3. Trailing Stop: aggiorna SL ad ogni mossa favorevole
        Restituisce lista di azioni eseguite.
        """
        mt5 = mt5_module
        actions = []
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return actions

        for pos in positions:
            if pos.magic != magic:
                continue

            ticket  = pos.ticket
            entry   = pos.price_open
            curr    = pos.price_current
            sl      = pos.sl
            tp      = pos.tp
            vol     = pos.volume
            is_buy  = (pos.type == 0)

            # Init stato se nuovo ticket
            if ticket not in self._pos_state:
                self._pos_state[ticket] = {
                    'be_done':      False,
                    'partial_done': False,
                    'ts_price':     None,
                    'ts_step':      current_atr * 0.5 if current_atr else 5.0,
                    'tp2':          abs(tp - entry) * 0.5 if tp else None,
                }

            ps = self._pos_state[ticket]
            dist = (curr - entry) if is_buy else (entry - curr)

            # ── 1. PARZIALIZZAZIONE ───────────────────────────────────────
            if not ps['partial_done'] and ps['tp2'] is not None:
                if dist >= ps['tp2']:
                    partial_vol = self._round_lot(vol * 0.5)
                    if partial_vol >= 0.01:
                        ok = self._close_partial(mt5, pos, partial_vol, symbol)
                        if ok:
                            ps['partial_done'] = True
                            log.info(f"✂️  Parziale ticket#{ticket}: chiusi {partial_vol} lot @ dist=${dist:.2f}")
                            actions.append({'type': 'partial', 'ticket': ticket, 'lot': partial_vol})
                            # Dopo parziale, sposta SL a BE
                            ps['be_done'] = False  # forza BE check immediato

            # ── 2. BREAK EVEN ─────────────────────────────────────────────
            if not ps['be_done'] and tp:
                # Se abbiamo un be_trigger specifico salvato o dedotto
                tp_dist = abs(tp - entry)
                be_trigger = ps.get('be_trigger') or (tp_dist * 0.40)
                
                if dist >= be_trigger:
                    be_sl = round(entry + 0.02, 2) if is_buy else round(entry - 0.02, 2)
                    if (is_buy and sl < be_sl) or (not is_buy and (sl == 0 or sl > be_sl)):
                        ok = self._modify_sl(mt5, pos, be_sl, tp, symbol)
                        if ok:
                            ps['be_done'] = True
                            log.info(f"🛡️  BE ticket#{ticket}: SL → {be_sl:.2f} (entry={entry:.2f})")
                            actions.append({'type': 'be', 'ticket': ticket, 'sl': be_sl})

            # ── 3. TRAILING STOP ──────────────────────────────────────────
            if ps['be_done']:   # attiva trailing solo dopo BE
                ts_step = ps['ts_step']
                if is_buy:
                    ideal_sl = round(curr - ts_step, 2)
                    if ideal_sl > sl:
                        ok = self._modify_sl(mt5, pos, ideal_sl, tp, symbol)
                        if ok:
                            ps['ts_price'] = curr
                            log.info(f"📈 Trailing ticket#{ticket}: SL → {ideal_sl:.2f} (+{(ideal_sl-entry):.2f})")
                            actions.append({'type': 'trail', 'ticket': ticket, 'sl': ideal_sl})
                else:
                    ideal_sl = round(curr + ts_step, 2)
                    if sl == 0 or ideal_sl < sl:
                        ok = self._modify_sl(mt5, pos, ideal_sl, tp, symbol)
                        if ok:
                            ps['ts_price'] = curr
                            log.info(f"📉 Trailing ticket#{ticket}: SL → {ideal_sl:.2f} (-{(entry-ideal_sl):.2f})")
                            actions.append({'type': 'trail', 'ticket': ticket, 'sl': ideal_sl})

        # Rimuovi stato per ticket chiusi
        open_tickets = {p.ticket for p in (positions or [])}
        for t in list(self._pos_state.keys()):
            if t not in open_tickets:
                del self._pos_state[t]

        return actions

    # ── HELPERS ────────────────────────────────────────────────────────────────
    def _round_lot(self, lot: float) -> float:
        """Arrotonda il lot al passo broker e applica cap min/max."""
        lot = max(0.01, min(self.max_lot, lot))
        steps = round(lot / self.lot_step)
        return round(steps * self.lot_step, 2)

    def _modify_sl(self, mt5, pos, new_sl: float, tp: float, symbol: str) -> bool:
        """Modifica lo SL di una posizione aperta."""
        req = {
            'action':   mt5.TRADE_ACTION_SLTP,
            'symbol':   symbol,
            'position': pos.ticket,
            'sl':       new_sl,
            'tp':       tp,
        }
        result = mt5.order_send(req)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            return True
        log.warning(f"⚠️  Modifica SL fallita ticket#{pos.ticket}: {result.comment if result else 'err'}")
        return False

    def _close_partial(self, mt5, pos, vol: float, symbol: str) -> bool:
        """Chiude parzialmente una posizione."""
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return False
        close_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
        price = tick.bid if pos.type == 0 else tick.ask
        req = {
            'action':       mt5.TRADE_ACTION_DEAL,
            'symbol':       symbol,
            'volume':       vol,
            'type':         close_type,
            'position':     pos.ticket,
            'price':        price,
            'deviation':    20,
            'magic':        pos.magic,
            'comment':      'TF-AI partial',
            'type_time':    mt5.ORDER_TIME_GTC,
            'type_filling': mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(req)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            return True
        log.warning(f"⚠️  Parziale fallita ticket#{pos.ticket}: {result.comment if result else 'err'}")
        return False

    # ── AI SCORE FETCH ─────────────────────────────────────────────────────────
    @staticmethod
    def fetch_ai_score(vercel_url: str, timeout: int = 5) -> float:
        """
        Recupera l'AI Score corrente dal tab Dashboard via Vercel DB.
        Ritorna un float 0-100 (default 50 se non disponibile).
        """
        import urllib.request
        try:
            url = f"{vercel_url}/api/db?action=mt5_get"
            req = urllib.request.Request(url, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                import json
                data = json.loads(r.read().decode())
                # La risposta ha struttura {ok, data: {..., ai_score: ...}}
                inner = data.get('data') or {}
                score = inner.get('ai_score')
                if score is not None:
                    return float(score)
                # Fallback: cerca a livello radice
                score = data.get('ai_score') or data.get('confidence')
                if score is not None:
                    return float(score)
        except Exception as e:
            pass  # usa default
        return 50.0  # score neutro di default


# ── SINGLETON ─────────────────────────────────────────────────────────────────
_rm_instance = None

def get_risk_manager(base_lot: float = 0.02, max_lot: float = 0.10) -> RiskManager:
    """Restituisce l'istanza singleton del RiskManager."""
    global _rm_instance
    if _rm_instance is None:
        _rm_instance = RiskManager(base_lot=base_lot, max_lot=max_lot)
    return _rm_instance
