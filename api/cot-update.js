// COT Data Updater — POST to this endpoint to fetch latest CFTC data and cache on GitHub
// CFTC publishes every Friday ~3:30pm ET for the previous Tuesday's positions
// Gold COMEX Report Code: 088691

const OWNER = process.env.GITHUB_OWNER || "alepunzi2895-alt";
const REPO  = process.env.GITHUB_REPO  || "tradeflow-ai";
const FILE  = "data/cot_data.json";
const TOKEN = process.env.GITHUB_TOKEN;

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  if (req.method === "OPTIONS") return res.status(200).end();

  try {
    // CFTC Disaggregated Futures Only report — current year
    const year = new Date().getFullYear();
    // Try multiple CFTC sources
    const sources = [
      // CFTC legacy format CSV (Gold is in "other" report)
      `https://www.cftc.gov/dea/newcot/f_year.txt`,
      // Alternative: Nasdaq Data Link (formerly Quandl) free tier
      `https://data.nasdaq.com/api/v3/datasets/CFTC/088691_FO_L_ALL.json?rows=2`
    ];

    let cotData = null;

    // Try Nasdaq Data Link (free, no key needed for COT)
    try {
      const r = await fetch(
        `https://data.nasdaq.com/api/v3/datasets/CFTC/088691_FO_L_ALL.json?rows=4`,
        { headers: { "User-Agent": "TradeFlowAI/1.0" } }
      );
      if (r.ok) {
        const d = await r.json();
        const rows = d?.dataset?.data;
        if (rows?.length > 0) {
          const latest = rows[0];
          // Columns: Date, Open Interest, Noncommercial Long, Noncommercial Short, 
          // Noncommercial Spreading, Commercial Long, Commercial Short, ...
          const reportDate = latest[0];
          const ncLong = parseInt(latest[2]);   // Large Spec Long
          const ncShort = parseInt(latest[3]);  // Large Spec Short
          const netLong = Math.round((ncLong - ncShort) / 1000); // in thousands

          // Previous week for change
          const prev = rows[1];
          const prevNet = prev ? Math.round((parseInt(prev[2]) - parseInt(prev[3])) / 1000) : netLong;
          const weekChange = netLong - prevNet;

          cotData = {
            ok: true,
            reportDate,
            netLong,           // Net position Large Spec (000s contracts)
            ncLong,            // Gross long
            ncShort,           // Gross short
            weekChange,        // Change from previous week
            weekChangePct: prevNet > 0 ? +((weekChange/prevNet)*100).toFixed(1) : 0,
            signal: netLong > 200 ? "EXTREME_LONG" :
                    netLong > 150 ? "ELEVATED_LONG" :
                    netLong < 50  ? "LOW_LONG" :
                    netLong < 20  ? "EXTREME_SHORT" : "NEUTRAL",
            interpretation: netLong > 200
              ? `⚠️ Speculatori eccessivamente long (${netLong}K) — rischio reversal alto`
              : netLong > 150
              ? `Large spec net long ${netLong}K — posizionamento rialzista sostenuto`
              : netLong < 50
              ? `✅ Speculatori poco posizionati (${netLong}K) — spazio per rally`
              : netLong < 20
              ? `🔥 Large spec net short — possibile short squeeze`
              : `Large spec neutro (${netLong}K) — nessun estremo`,
            source: "nasdaq_cftc",
            cached: new Date().toISOString()
          };
          console.log("COT loaded from Nasdaq:", cotData.reportDate, "net:", cotData.netLong, "K");
        }
      }
    } catch(e) { console.log("Nasdaq COT failed:", e.message); }

    // If Nasdaq failed, try CFTC direct
    if (!cotData) {
      try {
        const r = await fetch(
          `https://www.cftc.gov/dea/newcot/f_year.txt`,
          { headers: { "User-Agent": "Mozilla/5.0" } }
        );
        if (r.ok) {
          const txt = await r.text();
          // Find Gold line (code 088691)
          const lines = txt.split('\n').filter(l => l.includes('088691'));
          if (lines.length > 0) {
            const parts = lines[0].split(',');
            // Standard CFTC format: name, code, exchange, date, OI, NC_Long, NC_Short, NC_Spread, C_Long, C_Short...
            const reportDate = (parts[7] || '').trim().replace(/"/g, '');
            const ncLong = parseInt(parts[9]) || 0;
            const ncShort = parseInt(parts[10]) || 0;
            const netLong = Math.round((ncLong - ncShort) / 1000);
            cotData = {
              ok: true, reportDate, netLong, ncLong, ncShort, weekChange: 0,
              signal: netLong > 200 ? "EXTREME_LONG" : netLong < 50 ? "LOW_LONG" : "NEUTRAL",
              interpretation: `Large spec net ${netLong}K contratti`,
              source: "cftc_direct",
              cached: new Date().toISOString()
            };
          }
        }
      } catch(e) { console.log("CFTC direct failed:", e.message); }
    }

    if (!cotData) {
      return res.status(503).json({ ok: false, error: "Impossibile recuperare dati COT da CFTC/Nasdaq" });
    }

    // Save to GitHub for caching
    if (TOKEN) {
      try {
        const getR = await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/contents/${FILE}`, {
          headers: { "Authorization": `Bearer ${TOKEN}`, "Accept": "application/vnd.github+json", "User-Agent": "TradeFlowAI" }
        });
        const sha = getR.ok ? (await getR.json()).sha : null;
        await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/contents/${FILE}`, {
          method: "PUT",
          headers: { "Authorization": `Bearer ${TOKEN}`, "Content-Type": "application/json", "User-Agent": "TradeFlowAI" },
          body: JSON.stringify({
            message: `COT update ${cotData.reportDate}`,
            content: Buffer.from(JSON.stringify(cotData, null, 2)).toString("base64"),
            ...(sha ? { sha } : {})
          })
        });
        console.log("COT saved to GitHub");
      } catch(e) { console.log("GitHub COT save failed:", e.message); }
    }

    return res.status(200).json(cotData);

  } catch(err) {
    return res.status(500).json({ ok: false, error: err.message });
  }
}
