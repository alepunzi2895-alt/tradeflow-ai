# APEX Trading — Deploy su Vercel

## Struttura progetto
```
apex-trading/
├── api/
│   └── chat.js          ← proxy serverless (chiama Anthropic)
├── public/
│   └── index.html       ← app mobile completa
├── vercel.json
├── package.json
└── README.md
```

## Deploy in 4 passi

### 1. Crea repo GitHub
- Vai su github.com → "New repository"
- Nome: `apex-trading`
- Carica tutti i file di questa cartella

### 2. Collegati a Vercel
- Vai su vercel.com → "Add New Project"
- Importa il repo `apex-trading` da GitHub
- Clicca "Deploy" (lascia tutto default)

### 3. Aggiungi la API key di Anthropic
- Nel progetto Vercel → Settings → Environment Variables
- Aggiungi:
  - **Name:** `ANTHROPIC_API_KEY`
  - **Value:** la tua chiave da console.anthropic.com
- Clicca "Save" poi "Redeploy"

### 4. Apri sul telefono
- Vercel ti dà un URL tipo: `https://apex-trading-xxx.vercel.app`
- Apri su Safari iPhone
- Premi "Condividi" → "Aggiungi a schermata Home"
- Si installa come app nativa!

## Features
- 📈 Analisi TradingView + MT5 con screenshot
- ⚠️ Manipulation Score 1-10 automatico
- 🧠 Coach psicologico integrato (revenge, FOMO, paralisi)
- 📓 Journal trade con analisi AI
- 💾 Tutto salvato localmente sul telefono
- 🔒 API key sicura (mai esposta al client)