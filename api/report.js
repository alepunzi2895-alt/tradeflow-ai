// Generate trading reports: daily, weekly, monthly
// Also stores/retrieves trade coaching memory

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") return res.status(200).end();

  try {
    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey) return res.status(500).json({ error: "ANTHROPIC_API_KEY mancante" });

    const { type, entries, profile, period, memory } = req.body || {};

    if (!entries || !entries.length) {
      return res.status(400).json({ error: "Nessun trade fornito" });
    }

    // Filter by period
    const now = new Date();
    let filtered = entries;
    if (period === "day") {
      const today = now.toISOString().slice(0, 10);
      filtered = entries.filter(e => e.date === today);
    } else if (period === "week") {
      const weekAgo = new Date(now - 7 * 86400000).toISOString().slice(0, 10);
      filtered = entries.filter(e => e.date >= weekAgo);
    } else if (period === "month") {
      const monthAgo = new Date(now - 30 * 86400000).toISOString().slice(0, 10);
      filtered = entries.filter(e => e.date >= monthAgo);
    }

    if (!filtered.length) {
      return res.status(200).json({ ok: true, report: `Nessun trade nel periodo ${period} selezionato.` });
    }

    const wins = filtered.filter(e => e.result === "WIN").length;
    const losses = filtered.filter(e => e.result === "LOSS").length;
    const wr = Math.round(wins / filtered.length * 100);
    const pnl = filtered.reduce((s, e) => s + (parseFloat(e.pnl) || 0), 0);
    const avgWin = wins > 0 ? filtered.filter(e => e.result === "WIN").reduce((s, e) => s + (parseFloat(e.pnl) || 0), 0) / wins : 0;
    const avgLoss = losses > 0 ? Math.abs(filtered.filter(e => e.result === "LOSS").reduce((s, e) => s + (parseFloat(e.pnl) || 0), 0) / losses) : 0;
    const pf = avgLoss > 0 ? (avgWin * wins / (avgLoss * losses)).toFixed(2) : "N/D";

    const tradesSummary = filtered.map(e =>
      `${e.date}|${e.dir||e.direction}|E:${e.entry} SL:${e.sl} TP1:${e.tp1}|${e.result||'?'}|${e.pnl||0}$|${e.emo||e.emotion||'Neutro'}|${e.err||e.mistake||'Nessuno'}|${e.coaching||''}`