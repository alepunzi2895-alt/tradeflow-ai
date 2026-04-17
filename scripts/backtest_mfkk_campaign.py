import subprocess, json, os

tfs = ['M5', 'M15', 'M30', 'H1', 'H4']
results = {}

print("Inizio campagna backtest MFKK su tutti i timeframe...")
print("-" * 50)

for tf in tfs:
    file_path = f"data/xauusd_{tf.lower()}_mt5.json"
    if not os.path.exists(file_path):
        print(f"Skipping {tf}: file {file_path} non trovato.")
        continue
    
    out_file = f"backtests/results/mfkk_bt_{tf}.json"
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    cmd = [
        "python", "scripts/strategy-engine-v2.py",
        "--file", file_path,
        "--out", out_file
    ]
    
    print(f"Eseguendo backtest su {tf}...")
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        if os.path.exists(out_file):
            with open(out_file, 'r') as f:
                data = json.load(f)
                # S00_MFKK is in data['strategies']['S00_MFKK']['stats']
                stats_data = data.get('strategies', {}).get('S00_MFKK', {}).get('stats')
                if stats_data:
                    results[tf] = stats_data
                    found = True
                if not found:
                    print(f"S00_MFKK non trovato nei risultati di {tf}")
        else:
            print(f"Output file {out_file} non creato.")
    except Exception as e:
        print(f"Errore su {tf}: {e}")

# Display Summary
print("\n" + "="*80)
print(f"{'TF':<6} | {'Net P&L':<10} | {'PF':<6} | {'Win%':<6} | {'Trades':<6} | {'DD':<6}")
print("-" * 65)

for tf in tfs:
    res = results.get(tf)
    if not res: continue
    
    pnl = res['pnl']
    pf = res['pf']
    wr = res['wr']
    tr = res['n']
    dd = res['dd']
    
    print(f"{tf:<6} | {pnl:10.2f} | {pf:6.2f} | {wr:6.1f} | {tr:6} | {dd:6.2f}")

print("="*65)
