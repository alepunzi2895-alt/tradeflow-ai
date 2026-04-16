// TradeFlow AI — Standalone Express Server
// Bridging Vercel Serverless Handlers for VPS Deployment

import express from 'express';
import path from 'path';
import { fileURLToPath } from 'url';
import 'dotenv/config';

// Import Vercel handlers
import dbHandler from './api/db.js';
import priceHandler from './api/price.js';
import analysisHandler from './api/analysis.js';
import chatHandler from './api/chat.js';
import reportHandler from './api/report.js';
import webhookHandler from './api/webhook.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// Mock Vercel req/res bridge
const vercelBridge = (handler) => async (req, res) => {
    // Vercel's res.status().json() / res.setHeader() simulation
    const resProxy = {
        status: (code) => {
            res.status(code);
            return resProxy;
        },
        json: (data) => {
            res.json(data);
            return resProxy;
        },
        setHeader: (name, value) => {
            res.setHeader(name, value);
            return resProxy;
        },
        end: () => {
            res.end();
            return resProxy;
        }
    };

    // Vercel puts query in req.query and body in req.body (Express does too)
    try {
        await handler(req, resProxy);
    } catch (error) {
        console.error('API Error:', error);
        res.status(500).json({ ok: false, error: error.message });
    }
};

// --- API ROUTES (Matching vercel.json rewrites) ---

// DB / Auth / KB / MyFxBook
app.all('/api/db', vercelBridge(dbHandler));
app.all('/api/auth', vercelBridge(dbHandler));
app.all('/api/kb', vercelBridge(dbHandler));
app.all('/api/myfxbook', vercelBridge(dbHandler));

// Prices
app.all('/api/price', vercelBridge(priceHandler));
app.all('/api/tvprice', vercelBridge(priceHandler));
app.all('/api/candles', vercelBridge(priceHandler));

// Analysis
app.all('/api/market', vercelBridge(analysisHandler));
app.all('/api/indicators', vercelBridge(analysisHandler));
app.all('/api/cot-update', vercelBridge(analysisHandler));

// Other
app.all('/api/chat', vercelBridge(chatHandler));
app.all('/api/report', vercelBridge(reportHandler));
app.all('/api/webhook', vercelBridge(webhookHandler));

// SPA Redirect: All other routes to index.html
app.get('*', (req, res) => {
    res.sendFile(path.join(__dirname, 'public/index.html'));
});

// Start Server
app.listen(PORT, '0.0.0.0', () => {
    console.log(`\n🚀 TradeFlow AI Standalone Server`);
    console.log(`📍 URL: http://localhost:${PORT}`);
    console.log(`📂 Serving static files from /public`);
    console.log(`🛠️  API Bridge active for /api/*\n`);
});
