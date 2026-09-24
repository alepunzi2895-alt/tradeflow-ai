// Validazione delle specifiche del composer (stessi limiti di scripts/strategy_spec.py::validate).
// La specifica viaggia in coda come JSON e la esegue il worker: qui si scarta tutto ciò che non
// è nello schema (niente campi extra, numeri nei limiti), prima di scriverla nel DB.
import { fail } from './security.js';
import { instrument } from './instruments.js';

export const CATALOG = ['macd','macdSignal','macdHist','adx','diPlus','diMinus','close','sma','ema','rsi','atr','roc','momentum','std','bbUpper','bbLower','stoch','williams','cci','donHigh','donLow','volume','obv'];
const OPS = ['gt','lt','crossUp','crossDown'];
export const SPEC_TFS = ['M5','M15','M30','H1','H4','D1'];
const num = (v, lo, hi, what) => { const x = Number(v); if (!Number.isFinite(x) || x < lo || x > hi) throw fail(400, `${what}: da ${lo} a ${hi}`); return x; };
const int = (v, lo, hi, what) => Math.round(num(v, lo, hi, what));

export function cleanSpec(s) {
  if (!s || typeof s !== 'object') throw fail(400, 'Specifica mancante');
  const inst = instrument(s.instrument);
  if (!inst) throw fail(400, 'Strumento non nel registro');
  const tf = String(s.tf || '').toUpperCase();
  if (!SPEC_TFS.includes(tf)) throw fail(400, 'Timeframe non supportato');
  if (!['long','short'].includes(s.direction)) throw fail(400, 'Direzione: long o short');
  if (!Array.isArray(s.rules) || s.rules.length < 1 || s.rules.length > 8) throw fail(400, 'Da 1 a 8 regole');
  const rules = s.rules.map(r => {
    if (!CATALOG.includes(r?.left) || !OPS.includes(r?.op)) throw fail(400, 'Regola non valida');
    if (r.right !== 'number' && !CATALOG.includes(r.right)) throw fail(400, 'Confronto non valido');
    return { left: r.left, period: int(r.period, 2, 250, 'Periodo'), op: r.op, right: r.right,
             value: r.right === 'number' ? num(r.value, -1e12, 1e12, 'Soglia') : 0, rightPeriod: int(r.rightPeriod ?? 14, 2, 250, 'Periodo confronto') };
  });
  const ex = s.exit || {}, st = ex.stop || {};
  let stop;
  if (st.type === 'atr') stop = { type: 'atr', mult: num(st.mult, 0.2, 10, 'Stop ATR×'), period: int(st.period ?? 14, 2, 250, 'Periodo ATR') };
  else if (st.type === 'pct') stop = { type: 'pct', value: num(st.value, 0.01, 50, 'Stop %') };
  else if (st.type === 'donchian') stop = { type: 'donchian', period: int(st.period, 2, 250, 'Barre Donchian'), buffer_atr: num(st.buffer_atr ?? 0.3, 0, 5, 'Buffer ATR') };
  else throw fail(400, 'Tipo di stop non valido');
  const partial = ex.partial ? { at_r: num(ex.partial.at_r, 0.2, 10, 'Parziale a R'), fraction: num(ex.partial.fraction, 0.1, 0.9, 'Quota parziale') } : null;
  const session = s.session ? { from: int(s.session.from, 0, 23, 'Sessione da'), to: int(s.session.to, 1, 24, 'Sessione a') } : null;
  if (session && session.to <= session.from) throw fail(400, 'Sessione: l’ora di fine deve seguire quella di inizio');
  return {
    v: 1, name: String(s.name || 'Esperimento').slice(0, 80), instrument: inst.id, tf, direction: s.direction, rules, session,
    exit: { stop, take_r: num(ex.take_r, 0.2, 20, 'Target R'), partial,
            time_stop_bars: ex.time_stop_bars ? int(ex.time_stop_bars, 1, 2000, 'Uscita a tempo') : null },
    max_trades_per_day: int(s.max_trades_per_day ?? 10, 1, 50, 'Trade al giorno'),
  };
}
