// TradeFlow AI — api/myfxbook.js
// Proxy per le API ufficiali MyFxBook

const BASE = 'https://www.myfxbook.com/api';

async function fetchMfx(path, ms = 9000) {
  const ctrl = new AbortController();
  const tid = setTimeout(() => ctrl.abort(), ms);
  try {
    const r = await fetch(`${BASE}${path}`, {
      signal: ctrl.signal,
      headers: { 'Accept': 'application/json' }
    });
    clearTimeout(tid);
    const text = await r.text();
    // MyFxBook sometimes returns malformed JSON — try/catch
    try { return JSON.parse(text); }
    catch(e) { console.error('[myfxbook] JSON parse error:', text.slice(0,200)); throw new Error('Risposta non valida da MyFxBook'); }
  } catch (e) {
    clearTimeout(tid);
    throw e;
  }
}

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ error: true, message: 'Method not allowed' });

  let body = {};
  try {
    body = typeof req.body === 'string' ? JSON.parse(req.body) : req.body || {};
  } catch (e) {
    return res.status(400).json({ error: true, message: 'Invalid JSON' });
  }

  const { action, email, password, session, accountId } = body;

  try {

    // ── LOGIN ──────────────────────────────────────────────
    if (action === 'login') {
      if (!email || !password) return res.status(400).json({ error: true, message: 'Email e password richiesti.' });

      const d = await fetchMfx(`/login.json?email=${encodeURIComponent(email)}&password=${encodeURIComponent(password)}`);
      console.log('[myfxbook] login response error:', d.error, 'session:', d.session ? 'YES' : 'NO');

      // d.error can be boolean false or string "false" — treat both as ok
      const hasError = d.error === true || d.error === 'true';
      if (hasError || !d.session) {
        return res.json({ error: true, message: d.message || 'Login fallito. Verifica email e password MyFxBook.' });
      }

      return res.json({ ok: true, session: d.session });
    }

    // ── ACCOUNTS ──────────────────────────────────────────
    if (action === 'accounts') {
      if (!session) return res.status(400).json({ error: true, message: 'Session mancante.' });

      const d = await fetchMfx(`/get-my-accounts.json?session=${session}`);
      console.log('[myfxbook] accounts response error:', d.error, 'count:', Array.isArray(d.accounts) ? d.accounts.length : 'N/A');

      const hasError = d.error === true || d.error === 'true';
      if (hasError) return res.json({ error: true, message: d.message || 'Sessione scaduta. Rieffettua il login.' });

      const raw = Array.isArray(d.accounts) ? d.accounts : [];

      const accounts = raw.map(a => ({
        id: String(a.id || ''),
        name: a.name || 'Account',
        balance: a.balance || 0,
        equity: a.equity || 0,
        gain: a.gain || 0,
        drawdown: a.drawdown || 0,
        currency: a.currency || 'USD',
        broker: a.broker || '',
        server: typeof a.server === 'object' ? (a.server?.name || '') : (a.server || ''),
        deposits: a.deposits || 0,
        profit: a.profit || 0,
        wonTrades: a.wonTrades || 0,
        lostTrades: a.lostTrades || 0,
        totalTrades: (a.wonTrades || 0) + (a.lostTrades || 0),
        profitFactor: a.profitFactor || 0,
        bestTrade: a.bestTrade || 0,
        worstTrade: a.worstTrade || 0,
        lastUpdateDate: a.lastUpdateDate || '',
      }));

      console.log('[myfxbook] returning', accounts.length, 'accounts');
      return res.json({ ok: true, accounts });
    }

    // ── HISTORY ──────────────────────────────────────────
    if (action === 'history') {
      if (!session || !accountId) return res.status(400).json({ error: true, message: 'Session e accountId richiesti.' });

      const d = await fetchMfx(`/get-history.json?session=${session}&id=${encodeURIComponent(accountId)}`);

      const hasError = d.error === true || d.error === 'true';
      if (hasError) return res.json({ error: true, message: d.message || 'Impossibile caricare storico.' });

      return res.json({ ok: true, history: d.history || [] });
    }

    // ── OPEN TRADES ──────────────────────────────────────
    if (action === 'open') {
      if (!session || !accountId) return res.status(400).json({ error: true, message: 'Session e accountId richiesti.' });

      const d = await fetchMfx(`/get-open-trades.json?session=${session}&id=${encodeURIComponent(accountId)}`);

      const hasError = d.error === true || d.error === 'true';
      if (hasError) return res.json({ error: true, message: d.message || 'Impossibile caricare posizioni aperte.' });

      return res.json({ ok: true, openTrades: d.openTrades || [] });
    }

    // ── OUTLOOK ──────────────────────────────────────────
    if (action === 'outlook') {
      const sym = body.symbol || 'XAUUSD';
      const d = await fetchMfx(`/get-community-outlook.json?session=${session||''}&symbols=${encodeURIComponent(sym)}`);
      return res.json({ ok: true, outlook: d });
    }

    // ── LOGOUT ──────────────────────────────────────────
    if (action === 'logout') {
      if (session) {
        try { await fetchMfx(`/logout.json?session=${session}`); } catch (_) {}
      }
      return res.json({ ok: true });
    }

    return res.status(400).json({ error: true, message: `Azione "${action}" non supportata.` });

  } catch (e) {
    console.error('[myfxbook] error:', e.message);
    if (e.name === 'AbortError') return res.status(504).json({ error: true, message: 'MyFxBook non risponde (timeout). Riprova.' });
    return res.status(500).json({ error: true, message: 'Errore server: ' + e.message });
  }
}
