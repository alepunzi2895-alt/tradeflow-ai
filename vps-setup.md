# Guida Installazione VPS (Approccio Ibrido)

In questo scenario, la Dashboard rimane su **Vercel** e sulla VPS Windows facciamo girare solo il **Bot Python**.

## 1. Prerequisiti
- **VPS Windows**: Windows Server 2019/2022 o Windows 10/11.
- **MetaTrader 5**: Installato sulla VPS e loggato al tuo account.

## 2. Installazione Software
Scarica e installa solo Python sul server:

1. **Python (3.10+)**: [python.org](https://python.org/).
   - **IMPORTANTE**: Spunta la casella "Add Python to PATH".
2. **Git**: [git-scm.com](https://git-scm.com/).

## 3. Setup del Bot

Apri il terminale (PowerShell) sulla VPS:

```powershell
# 1. Clona il progetto (o copia solo la cartella scripts)
git clone https://github.com/tuo-username/tradeflow-ai.git
cd tradeflow-ai

# 2. Installa le dipendenze Python
pip install MetaTrader5 pandas requests pytz python-dotenv
```

## 4. Configurazione (.env)

1. Crea il file `.env` nella cartella principale del progetto:
   ```powershell
   copy .env.example .env
   ```
2. Modifica il file `.env` aggiungendo i tuoi dati:
   - `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`
   - `VERCEL_URL=https://tradeflow-ai-delta.vercel.app`
   - `MT5_BOT_SECRET` (deve coincidere con quello su Vercel)

## 5. Avvio 24/7 con PM2

Utilizzeremo PM2 per assicurarci che il bot non si chiuda mai.

1. Installa PM2 (richiede Node.js, se non vuoi Node puoi usare Task Scheduler di Windows, ma PM2 è più affidabile):
   ```powershell
   # Nota: richiede Node.js installato solo per far girare PM2
   npm install -g pm2
   ```

2. Avvia il Bot:
   ```powershell
   pm2 start scripts/mt5-bot.py --name "tf-bot" --interpreter python
   ```

3. Monitoraggio:
   ```powershell
   pm2 status
   pm2 logs tf-bot
   ```

## 6. Configurazione MetaTrader 5
- Apri MT5 -> Strumenti -> Opzioni -> Expert Advisors.
- Spunta **"Permetti Trading Algoritmico"**.
