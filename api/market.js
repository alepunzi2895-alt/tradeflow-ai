// TradeFlow AI — api/market.js
// Proxy per dati di mercato (Calendario, Sentiment, etc)

export default async function handler(req, res) {
  const { type, symbol } = req.query;

  try {
    // ── CALENDARIO ECONOMICO ────────────────────────────────
    if (type === 'calendar') {
      const URL = 'https://nfs.faireconomy.media/ff_calendar_thisweek.json';
      const r = await fetch(URL);
      if (!r.ok) throw new Error('ForexFactory non risponde');
      
      const data = await r.json();
      
      // Filtriamo eventi rilevanti
      const filtered = data.filter(e => {
        const country = (e.currency || e.country || "").toUpperCase();
        const impact = (e.impact || "").toLowerCase();
        return ["USD", "EUR", "GBP", "JPY", "AUD"].includes(country) && 
               (impact === "high" || impact === "medium");
      });

      const events = filtered.slice(0, 20).map(e => ({
        id: e.id || Math.random().toString(36).substr(2, 9),
        time: e.date || e.time || new Date().toISOString(),
        currency: (e.currency || e.country || "USD").toUpperCase(),
        event: e.event || e.title || "Economic Event",
        impact: e.impact || "High"
      }));

      return res.status(200).json({ ok: true, events });
    }

    // ── ALTRO (SENTIMENT FALLBACK) ──────────────────────────
    if (type === 'sentiment') {
      // Potremmo aggiungere un fallback qui se MyFxBook fallisce
      return res.status(200).json({ ok: false, message: 'Not implemented' });
    }

    return res.status(400).json({ ok: false, message: 'Type non supportato' });
  } catch (e) {
    console.error('[market] error:', e.message);
    return res.status(500).json({ ok: false, message: e.message });
  }
}
