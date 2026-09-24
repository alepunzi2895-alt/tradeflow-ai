"""Final broker-aware guard for every new position. No terminal initialization.

Loss calculations use MT5's account-currency contract conversion, not a fixed
USD/point assumption. Unknown inputs fail closed; reductions/closures are separate.
"""
import math
import os
from decimal import Decimal, ROUND_FLOOR
from datetime import datetime, timezone, timedelta

# Freschezza della quotazione: MT5 riporta tick.time e deal.time in ORA DEL SERVER del broker,
# non in UTC. Fix 2026-09-24: il controllo originale (-5 ≤ now − tick.time ≤ 60, dal 2026-09-18)
# confrontava UTC con ora broker (XM = UTC+3 d'estate) → ogni nuovo ordine veniva rifiutato come
# "Quotazione scaduta". Ora il tempo del tick è riportato in UTC con il fuso del broker.
STALE_TOLERANCE_S = 180     # tollera ~3 min di scarto dell'orologio del PC (misurato: 109 s su questo PC)


def _last_sunday(year, month):
    d = datetime(year, month + 1, 1, tzinfo=timezone.utc) - timedelta(days=1) if month < 12 else datetime(year, 12, 31, tzinfo=timezone.utc)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def broker_utc_offset(now):
    """Secondi da sommare all'UTC per ottenere l'ora del server del broker.
    BROKER_UTC_OFFSET (ore) nel .env ha la precedenza; altrimenti EET/EEST (XM e molti broker MT5):
    +3h tra l'ultima domenica di marzo e l'ultima di ottobre (01:00 UTC), altrimenti +2h.
    Calcolato a mano: zoneinfo su Windows richiede il pacchetto tzdata, che può mancare."""
    env = os.getenv('BROKER_UTC_OFFSET')
    if env not in (None, ''):
        return float(env) * 3600
    start = _last_sunday(now.year, 3).replace(hour=1)
    end = _last_sunday(now.year, 10).replace(hour=1)
    return 3 * 3600 if start <= now < end else 2 * 3600


class OrderRejected(ValueError):
    pass


def floor_volume(requested, cap, minimum, maximum, step):
    values = (requested, cap, minimum, maximum, step)
    if any(not math.isfinite(v) or v <= 0 for v in values):
        return 0.0
    volume = min(Decimal(str(requested)), Decimal(str(cap)), Decimal(str(maximum)))
    unit = Decimal(str(step))
    volume = (volume / unit).to_integral_value(rounding=ROUND_FLOOR) * unit
    return float(volume) if volume >= Decimal(str(minimum)) else 0.0


def guard_entry(mt5, request, enabled, max_risk=.02, portfolio_risk=.04, now=None):
    if not enabled:
        raise OrderRejected('Nuovi ingressi disabilitati o configurazione non disponibile')
    account = mt5.account_info()
    info = mt5.symbol_info(request['symbol'])
    tick = mt5.symbol_info_tick(request['symbol'])
    now = now or datetime.now(timezone.utc)
    if not account or not info or not tick or not math.isfinite(account.equity) or account.equity <= 0:
        raise OrderRejected('Conto o simbolo non disponibili')
    offset = broker_utc_offset(now)
    age = now.timestamp() + offset - tick.time
    if not -STALE_TOLERANCE_S <= age <= STALE_TOLERANCE_S:
        raise OrderRejected(f'Quotazione scaduta ({age:.0f}s)')
    buy = request['type'] == mt5.ORDER_TYPE_BUY
    price, sl, tp = (request[k] for k in ('price','sl','tp'))
    if not all(math.isfinite(v) and v > 0 for v in (price,sl,tp)):
        raise OrderRejected('Prezzi non validi')
    if not (sl < price < tp if buy else tp < price < sl):
        raise OrderRejected('Stop e target sul lato errato')
    positions = mt5.positions_get()
    if positions is None:
        raise OrderRejected('Posizioni non disponibili')
    if len(positions) >= 3:
        raise OrderRejected('Limite complessivo di tre posizioni')
    existing_risk = 0.0
    for p in positions:
        if not p.sl or p.sl <= 0:
            raise OrderRejected('Posizione senza stop: rischio complessivo sconosciuto')
        loss = mt5.order_calc_profit(p.type,p.symbol,p.volume,p.price_open,p.sl)
        if loss is None or not math.isfinite(loss):
            raise OrderRejected('Rischio posizioni non calcolabile')
        existing_risk += max(0.,-loss)
    # Include all strategies and manual deals; do not discard losses of blocked strategies.
    midnight = now.replace(hour=0,minute=0,second=0,microsecond=0)
    monday = midnight-timedelta(days=midnight.weekday())
    deals = mt5.history_deals_get(monday,now)
    if deals is None:
        raise OrderRejected('Storico conto non disponibile')
    traded = [d for d in deals if d.type in (mt5.ORDER_TYPE_BUY,mt5.ORDER_TYPE_SELL)]
    def realized(rows):
        return sum(d.profit + d.commission + d.swap + getattr(d,'fee',0.) for d in rows)
    daily = realized([d for d in traded if d.time - offset >= midnight.timestamp()])
    weekly = realized(traded)
    floating = account.equity-account.balance
    if daily+floating <= -.03*max(account.balance-daily,1):
        raise OrderRejected('Circuit breaker giornaliero 3%')
    if weekly+floating <= -.06*max(account.balance-weekly,1):
        raise OrderRejected('Circuit breaker settimanale 6%')
    probe = info.volume_min
    loss = mt5.order_calc_profit(request['type'],request['symbol'],probe,price,sl)
    if loss is None or not math.isfinite(loss) or loss >= 0:
        raise OrderRejected('Perdita allo stop non calcolabile')
    per_lot = -loss/probe
    budget = min(account.equity*max_risk,account.equity*portfolio_risk-existing_risk)
    # Reserve 10% for estimated execution costs; gaps can still exceed stop loss.
    volume = floor_volume(request['volume'],budget/(per_lot*1.1),info.volume_min,info.volume_max,info.volume_step)
    if not volume:
        raise OrderRejected('Lotto minimo superiore al budget di rischio')
    margin = mt5.order_calc_margin(request['type'],request['symbol'],volume,price)
    if margin is None or not math.isfinite(margin) or margin > account.margin_free:
        raise OrderRejected('Margine insufficiente o non calcolabile')
    return {**request,'volume':volume}
