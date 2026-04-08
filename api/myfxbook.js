// TradeFlow AI — api/myfxbook.js
// Proxy per le API ufficiali MyFxBook (nessuna password salvata)

const BASE = 'https://www.myfxbook.com/api';

async function fetchMfx(path, ms = 8000) {
  const ctrl = new AbortController();
  const tid = setTimeout(() => ctrl.abort(), ms);
  try {
    const r = await fetch(`${BASE}${path}`, { signal: ctrl.signal });
    clearTimeout(tid);
    return r;
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
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  let body = {};
  try {
    body = typeof req.body === 'string' ? JSON.parse(req.body) : req.body || {};
  } catch (e) {
    return res.status(400).json({ error: 'Invalid JSON' });
  }

  const { action, email, password, session, accountId } = body;

  try {
    // ── LOGIN ──────────────────────────────────────────────
    if (action === 'login') {
      if (!email || !password) return res.status(400).json({ error: true, message: 'Email e password richiesti.' });

      const r = await fetchMfx(`/login.json?email=${encodeURIComponent(email)}&password=${encodeURIComponent(password)}`);
      const d = await r.json();

      if (d.error || !d.session) {
        return res.json({ error: true, message: d.message || 'Login fallito. Verifica email e password MyFxBook.' });
      }

      // Non salviamo la password — solo il session token temporaneo
      return res.json({ ok: true, session: d.session });
    }

    // ── ACCOUNTS ──────────────────────────────────────────
    if (action === 'accounts') {
      if (!session) return res.status(400).json({ error: true, message: 'Session mancante.' });

      const r = await fetchMfx(`/get-my-accounts.json?session=${encodeURIComponent(session)}`);
      const d = await r.json();

      if (d.error) return res.json({ error: true, message: d.message || 'Sessione scaduta. Rieffettua il login.' });

      const accounts = (d.accounts || []).map(a => ({
        id: a.id,
        name: a.name,
        balance: a.balance,
        equity: a.equity,
        gain: a.gain,
        drawdown: a.drawdown,
        currency: a.currency,
        broker: a.broker,
        server: a.server,
        deposits: a.deposits,
        profit: a.profit,
        pips: a.pips,
        lots: a.lots,
        wonTrades: a.wonTrades,
        lostTrades: a.lostTrades,
        totalTrades: a.totalTrades,
        profitFactor: a.profitFactor,
        bestTrade: a.bestTrade,
        worstTrade: a.worstTrade,
        avgWinTrade: a.avgWinTrade,
        avgLossTrade: a.avgLossTrade,
        lastUpdateDate: a.lastUpdateDate,
      }));

      return res.json({ ok: true, accounts });
    }

    // ── HISTORY ──────────────────────────────────────────
    if (action === 'history') {
      if (!session || !accountId) return res.status(400).json({ error: true, message: 'Session e accountId richiesti.' });

      const r = await fetchMfx(`/get-history.json?session=${encodeURIComponent(session)}&id=${encodeURIComponent(accountId)}`);
      const d = await r.json();

      if (d.error) return res.json({ error: true, message: d.message || 'Impossibile caricare storico.' });

      return res.json({ ok: true, history: d.history || [] });
    }

    // ── OPEN TRADES ──────────────────────────────────────
    if (action === 'open') {
      if (!session || !accountId) return res.status(400).json({ error: true, message: 'Session e accountId richiesti.' });

      const r = await fetchMfx(`/get-open-trades.json?session=${encodeURIComponent(session)}&id=${encodeURIComponent(accountId)}`);
      const d = await r.json();

      if (d.error) return res.json({ error: true, message: d.message || 'Impossibile caricare posizioni aperte.' });

      return res.json({ ok: true, openTrades: d.openTrades || [] });
    }

    // ── LOGOUT ──────────────────────────────────────────
    if (action === 'logout') {
      if (!session) return res.json({ ok: true });
      try {
        await fetchMfx(`/logout.json?session=${encodeURIComponent(session)}`);
      } catch (_) { /* fire and forget */ }
      return res.json({ ok: true });
    }

    return res.status(400).json({ error: true, message: `Azione "${action}" non supportata.` });

  } catch (e) {
    console.error('[myfxbook]', e.message);
    if (e.name === 'AbortError') return res.status(504).json({ error: true, message: 'MyFxBook timeout. Riprova.' });
    return res.status(500).json({ error: true, message: 'Errore server: ' + e.message });
  }
}
