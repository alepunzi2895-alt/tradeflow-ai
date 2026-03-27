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
    ).join("\n");

    const memoryCtx = memory ? `\nMEMORIA PRECEDENTE:\n${memory}` : "";
    const periodLabel = period === "day" ? "GIORNALIERO" : period === "week" ? "SETTIMANALE" : "MENSILE";

    let prompt = "";
    if (type === "report") {
      prompt = `Genera un REPORT ${periodLabel} COMPLETO per il trader ${profile?.name || "Alessandro"} su XAU/USD.

DATI PERIODO:
Trade totali: ${filtered.length} | Win: ${wins} | Loss: ${losses} | WR: ${wr}%
P&L totale: ${pnl >= 0 ? "+" : ""}${pnl.toFixed(0)}$ | Profit Factor: ${pf}
Avg Win: +${avgWin.toFixed(0)}$ | Avg Loss: -${avgLoss.toFixed(0)}$

STORICO TRADE:
${tradesSummary}
${memoryCtx}

Il report deve includere:
### 📊 STATISTICHE ${periodLabel}
[Metriche complete formattate]

### ✅ COSA STA ANDANDO BENE
[Pattern positivi, punti di forza emersi]

### 🎯 AREE DI MIGLIORAMENTO
[NON "errori" — usa linguaggio costruttivo: "opportunità di crescita", "da ottimizzare"]

### 📈 PROGRESSI RISPETTO AL PERIODO PRECEDENTE
[Confronto se disponibile dalla memoria]

### 🧠 PIANO DI SVILUPPO
[3 azioni concrete e misurabili per il prossimo periodo]

### 💪 SCORE DISCIPLINA: X/10
[Valutazione con motivazione costruttiva]`;
    } else if (type === "coaching") {
      // Single trade coaching
      const trade = filtered[0];
      prompt = `Analizza questo singolo trade XAU/USD e dai un coaching costruttivo breve (max 3 righe):
Trade: ${trade.dir||trade.direction} | Entry: ${trade.entry} | SL: ${trade.sl} | TP1: ${trade.tp1} | TP2: ${trade.tp2}
Risultato: ${trade.result} | P&L: ${trade.pnl}$ | Emozione: ${trade.emo||trade.emotion} | Errore: ${trade.err||trade.mistake}
Note: ${trade.notes || "nessuna"}

Profilo trader: ${profile?.name}, rischio ${profile?.risk}%, TP1 ${profile?.tp1}R TP2 ${profile?.tp2}R

Rispondi in italiano con 1 punto positivo e 1 cosa da ottimizzare. Tono costruttivo, non critico. Max 2 frasi.`;
    } else if (type === "progress") {
      prompt = `Analizza i progressi del trader ${profile?.name} su XAU/USD e crea una scheda di crescita.

TRADE RECENTI:
${tradesSummary}
${memoryCtx}

Genera:
### 🌟 PUNTI DI FORZA CONFERMATI
[Cosa sta migliorando concretamente]

### 🎯 FOCUS DI SVILUPPO
[1-2 aree chiave su cui concentrarsi — linguaggio positivo]

### 📊 TREND PERFORMANCE
[Sta migliorando? Plateau? Regressione? Con dati specifici]

### 💡 INSIGHT PSICOLOGICO
[Un'osservazione sul pattern emotivo/comportamentale]

Sii specifico, usa i dati. Tono da coach, non da critico.`;
    }

    const r = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": apiKey,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify({
        model: "claude-sonnet-4-20250514",
        max_tokens: 1500,
        system: "Sei TradeFlow AI, coach di trading professionale. Rispondi sempre in italiano. Usa linguaggio costruttivo, orientato alla crescita. Mai 'errori' — usa 'opportunità di miglioramento', 'da ottimizzare', 'area di sviluppo'.",
        messages: [{ role: "user", content: prompt }]
      })
    });

    const d = await r.json();
    if (d.error) throw new Error(d.error.message);
    const text = (d.content || []).filter(b => b.type === "text").map(b => b.text).join("\n").trim();

    return res.status(200).json({ ok: true, report: text, stats: { total: filtered.length, wins, losses, wr, pnl: pnl.toFixed(0), pf } });

  } catch (err) {
    return res.status(500).json({ ok: false, error: err.message });
  }
}
