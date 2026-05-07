"""
TradeFlow AI — News Guardian
═══════════════════════════════════════════════════════════════════
Monitora il calendario economico e regola il rischio attorno a
news ad alto impatto su USD/XAU.

Comportamento:
  • HIGH impact USD/XAU → pausa trading -30min / +60min
  • HIGH impact altre valute → riduzione rischio (risk_mult 0.5)
  • Nessuna news → risk_mult 1.0, paused False

Fonti: ForexFactory JSON (primary) → cache locale (fallback)
Refresh automatico ogni 6 ore.

USAGE da mt5-bot.py:
    from news_guardian import get_news_guardian
    ng = get_news_guardian()
    risk = ng.check_news_risk()
    if risk['paused']:
        log.warning(f"Trading in pausa: {risk['reason']}")
    elif risk['risk_mult'] < 1.0:
        lot_use *= risk['risk_mult']

USAGE standalone:
    python scripts/news_guardian.py [--hours 8]
"""
import json, os, sys, datetime, logging, urllib.request, urllib.error, ssl, argparse

log = logging.getLogger('tf-bot')

_BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR  = os.path.join(_BASE_DIR, '..', 'data')
CACHE_PATH = os.path.join(_DATA_DIR, 'news_calendar_cache.json')

# ── Config ────────────────────────────────────────────────────────────────────
PAUSE_BEFORE_MIN  = 30    # pausa N min prima dell'evento
PAUSE_AFTER_MIN   = 60    # pausa N min dopo l'evento
MEDIUM_RISK_MULT  = 0.50  # riduzione rischio per HIGH impact su altre valute
REFRESH_HOURS     = 6     # refresh calendario ogni N ore

HIGH_CURRENCIES   = {'USD', 'XAU', 'GOLD'}  # valute che impattano XAU
MEDIUM_CURRENCIES = {'EUR', 'GBP', 'JPY', 'CHF', 'AUD', 'CAD'}
HIGH_TAGS         = {'High', 'HIGH', 'high', '3', 'red'}
MEDIUM_TAGS       = {'Medium', 'MEDIUM', 'medium', '2', 'orange'}

# URL ForexFactory — ordinati per priorità, tutti tentati in sequenza
FF_URLS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
    "https://cdn-nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://cdn-nfs.faireconomy.media/ff_calendar_nextweek.json",
    "https://www.forexfactory.com/ff_calendar_thisweek.json",
]
BACKUP_URLS = []  # tutti già in FF_URLS

# ── SSL context (tolera cert issues su VPS Windows) ───────────────────────────
try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL = ssl.create_default_context()
    _SSL.check_hostname = False
    _SSL.verify_mode = ssl.CERT_NONE


# ── Date parsing ──────────────────────────────────────────────────────────────
def _parse_dt(date_str: str, time_str: str = '') -> datetime.datetime | None:
    """
    Parsa data/ora da ForexFactory, restituisce datetime UTC naive.
    Formato nuovo (2025+): date='2026-04-21T08:30:00-04:00' (ISO con timezone).
    Formato vecchio: date='04-10-2025', time='08:30am'.
    """
    import re as _re
    clean = date_str.strip()

    # Normalizza formato ForexFactory: MM-DD-YYYYThh:mm:ss → YYYY-MM-DDThh:mm:ss
    clean = _re.sub(r'^(\d{2})-(\d{2})-(\d{4})(T.+)$', r'\3-\1-\2\4', clean)

    # Nuovo formato FF: ISO con offset timezone (+HH:MM / -HH:MM)
    tz_m = _re.match(r'^(.+?)([+-])(\d{2}):(\d{2})$', clean)
    if tz_m:
        try:
            dt_local = datetime.datetime.fromisoformat(tz_m.group(1))
            offset = datetime.timedelta(hours=int(tz_m.group(3)), minutes=int(tz_m.group(4)))
            return dt_local - offset if tz_m.group(2) == '+' else dt_local + offset
        except ValueError:
            pass

    # ISO senza timezone
    try:
        return datetime.datetime.fromisoformat(clean)
    except ValueError:
        pass

    # Vecchio formato: date + time separati
    raw = (clean + ' ' + time_str.strip()).strip()
    for fmt in [
        '%m-%d-%Y %I:%M%p',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M',
        '%b %d, %Y %I:%M%p',
        '%B %d, %Y %I:%M%p',
    ]:
        try:
            return datetime.datetime.strptime(raw, fmt)
        except ValueError:
            pass
    return None


# ── NewsGuardian ──────────────────────────────────────────────────────────────

class NewsGuardian:
    """
    Monitora il calendario economico e fornisce check_news_risk()
    per integrare la pausa news nel loop del bot.
    """

    def __init__(self):
        self._events:     list  = []
        self._last_fetch: float = 0.0
        self._load_cache()

    # ── Cache I/O ─────────────────────────────────────────────────────────────

    def _load_cache(self):
        try:
            with open(CACHE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._events     = data.get('events', [])
            self._last_fetch = data.get('fetched_at', 0.0)
        except (FileNotFoundError, json.JSONDecodeError):
            self._events     = []
            self._last_fetch = 0.0

    def _save_cache(self):
        os.makedirs(_DATA_DIR, exist_ok=True)
        with open(CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump({
                'fetched_at': self._last_fetch,
                'count':      len(self._events),
                'events':     self._events,
            }, f, indent=2)

    # ── Fetch ─────────────────────────────────────────────────────────────────

    def _fetch_url(self, url: str) -> list:
        """Scarica e normalizza eventi da un URL ForexFactory."""
        try:
            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'TradeFlow-AI/1.0', 'Accept': 'application/json'}
            )
            with urllib.request.urlopen(req, context=_SSL, timeout=10) as resp:
                raw = json.loads(resp.read().decode('utf-8'))

            events = []
            for e in raw:
                impact = str(e.get('impact', '')).strip()
                # FF API 2026: campo rinominato 'currency' → 'country' (o entrambi presenti)
                currency = str(e.get('currency') or e.get('country') or '').upper().strip()

                is_high   = impact in HIGH_TAGS
                is_medium = impact in MEDIUM_TAGS
                is_xau    = currency in HIGH_CURRENCIES or currency in MEDIUM_CURRENCIES
                if not (is_high or is_medium) or not is_xau:
                    continue

                dt = _parse_dt(
                    str(e.get('date', '')),
                    str(e.get('time', ''))
                )
                if dt is None:
                    continue

                events.append({
                    'title':    str(e.get('title', '')).strip(),
                    'currency': currency,
                    'impact':   impact,
                    'dt':       dt.isoformat(),
                    'forecast': str(e.get('forecast', '')),
                    'previous': str(e.get('previous', '')),
                })
            return events

        except Exception as ex:
            log.warning(f"[NewsGuardian] fetch {url} failed: {type(ex).__name__}: {ex}")
            return []

    def refresh(self, force: bool = False) -> int:
        """
        Aggiorna il calendario se > REFRESH_HOURS ore fa.
        Ritorna il numero di eventi in cache.
        """
        import time as _time
        now_ts = _time.time()
        if not force and (now_ts - self._last_fetch) < REFRESH_HOURS * 3600:
            return len(self._events)

        all_events = []
        for url in FF_URLS + BACKUP_URLS:
            fetched = self._fetch_url(url)
            if fetched:
                all_events.extend(fetched)
                if len(all_events) >= 10:
                    break  # abbastanza dati, evita fetch inutili

        if all_events:
            seen = set()
            uniq = []
            for e in all_events:
                key = (e['dt'], e['title'], e['currency'])
                if key not in seen:
                    seen.add(key)
                    uniq.append(e)
            self._events     = sorted(uniq, key=lambda x: x['dt'])
            self._last_fetch = now_ts
            self._save_cache()
            log.info(f"[NewsGuardian] Calendario aggiornato: {len(self._events)} eventi")
        else:
            # Anche su fallimento aggiorna _last_fetch con retry delay di 30 min.
            # Senza questo, la cache vuota fa sì che refresh() venga ritentato ogni 60s
            # esaurendo il rate limit di ForexFactory (429).
            RETRY_DELAY_S = 1800  # riprova tra 30 minuti
            self._last_fetch = now_ts - REFRESH_HOURS * 3600 + RETRY_DELAY_S
            log.warning("[NewsGuardian] Tutti i fetch falliti — uso cache locale "
                        f"({len(self._events)} eventi). Prossimo retry fra 30 min.")

        return len(self._events)

    # ── Core check ────────────────────────────────────────────────────────────

    def check_news_risk(self, now_utc: datetime.datetime = None) -> dict:
        """
        Controlla se il momento attuale è nella finestra di pausa news.

        Ritorna:
            paused     (bool)  — ferma qualsiasi apertura di trade
            risk_mult  (float) — 0.0-1.0, moltiplica il lot size
            reason     (str)   — descrizione
            next_event (dict)  — prossimo evento rilevante ad alto impatto
            event      (dict)  — evento che ha scatenato la condizione
        """
        if now_utc is None:
            now_utc = datetime.datetime.utcnow()
        # Normalizza a naive UTC: il cache salva datetime naive, la sottrazione deve essere omogenea
        if now_utc.tzinfo is not None:
            now_utc = now_utc.replace(tzinfo=None)

        # Auto-refresh silenzioso
        self.refresh()

        paused          = False
        risk_mult       = 1.0
        reason          = "clear"
        triggered_event = None

        for e in self._events:
            try:
                evt_dt = datetime.datetime.fromisoformat(e['dt'])
            except ValueError:
                continue

            diff_min  = (evt_dt - now_utc).total_seconds() / 60
            is_high   = e['impact'] in HIGH_TAGS
            is_xau_usd = e['currency'] in HIGH_CURRENCIES

            if is_high and is_xau_usd:
                # Finestra pausa totale: [-AFTER, +BEFORE]
                if -PAUSE_AFTER_MIN <= diff_min <= PAUSE_BEFORE_MIN:
                    paused    = True
                    risk_mult = 0.0
                    reason    = (
                        f"⛔ NEWS HIGH ({e['currency']}): {e['title']} | "
                        f"{'tra ' + str(int(diff_min)) + 'min' if diff_min > 0 else str(int(-diff_min)) + 'min fa'}"
                    )
                    triggered_event = e
                    break  # pausa totale, non servono altri check

            elif is_high:
                # Alta importanza ma altra valuta → riduzione rischio
                if -30 <= diff_min <= 20 and risk_mult > MEDIUM_RISK_MULT:
                    risk_mult = MEDIUM_RISK_MULT
                    reason    = (
                        f"⚠️ NEWS MEDIUM RISK ({e['currency']}): {e['title']} | "
                        f"{'tra ' + str(int(diff_min)) + 'min' if diff_min > 0 else str(int(-diff_min)) + 'min fa'}"
                    )
                    triggered_event = e

        # Prossimo evento alto impatto USD/XAU
        next_event = None
        for e in self._events:
            try:
                dt = datetime.datetime.fromisoformat(e['dt'])
            except ValueError:
                continue
            if dt > now_utc and e['impact'] in HIGH_TAGS and e['currency'] in HIGH_CURRENCIES:
                mins = round((dt - now_utc).total_seconds() / 60)
                next_event = {**e, 'minutes_away': mins}
                break

        return {
            'paused':     paused,
            'risk_mult':  risk_mult,
            'reason':     reason,
            'next_event': next_event,
            'event':      triggered_event,
        }

    def get_upcoming_high_impact(self, hours_ahead: int = 8) -> list:
        """Lista eventi alto impatto USD/XAU nelle prossime N ore."""
        now_utc = datetime.datetime.utcnow()
        cutoff  = now_utc + datetime.timedelta(hours=hours_ahead)
        result  = []
        for e in self._events:
            try:
                dt = datetime.datetime.fromisoformat(e['dt'])
            except ValueError:
                continue
            if now_utc <= dt <= cutoff and e['impact'] in HIGH_TAGS:
                result.append({
                    **e,
                    'minutes_away': round((dt - now_utc).total_seconds() / 60),
                })
        return result


# ── Singleton ─────────────────────────────────────────────────────────────────
_instance: NewsGuardian = None


def get_news_guardian() -> NewsGuardian:
    global _instance
    if _instance is None:
        _instance = NewsGuardian()
    return _instance


# ── CLI standalone ────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import sys as _sys
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s [%(levelname)s] %(message)s')

    ap = argparse.ArgumentParser(description='News Guardian — mostra eventi imminenti')
    ap.add_argument('--hours', type=int, default=12, help='Ore in avanti da mostrare')
    ap.add_argument('--force', action='store_true', help='Forza re-fetch del calendario')
    cli = ap.parse_args()

    ng = get_news_guardian()
    ng.refresh(force=cli.force)

    print(f"\n── News Guardian — {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC ──")

    risk = ng.check_news_risk()
    status = "⛔ PAUSA TRADING" if risk['paused'] else (
        f"⚠️  RISCHIO RIDOTTO (×{risk['risk_mult']:.0%})" if risk['risk_mult'] < 1.0 else "✅ CLEAR"
    )
    print(f"Stato attuale: {status}")
    if risk['reason'] != 'clear':
        print(f"  → {risk['reason']}")

    upcoming = ng.get_upcoming_high_impact(hours_ahead=cli.hours)
    if upcoming:
        print(f"\nEventi HIGH IMPACT USD/XAU prossime {cli.hours}h:")
        for e in upcoming:
            mins = e['minutes_away']
            when = f"fra {mins}min" if mins > 0 else f"{-mins}min fa"
            print(f"  {e['dt'][11:16]} UTC ({when:>12})  {e['currency']:<4}  {e['title']}")
    else:
        print(f"\nNessun evento HIGH IMPACT USD/XAU nelle prossime {cli.hours}h.")

    if risk.get('next_event'):
        ne = risk['next_event']
        print(f"\nProssimo HIGH: {ne['title']} ({ne['currency']}) fra {ne['minutes_away']}min")
