import json
import os
from datetime import datetime

def sync():
    # File paths
    h1_file = 'strategy_engine_v2.json'
    m30_file = 'strategy_m30_results.json'
    m15_file = 'strategy_m15_results.json'
    out_file = 'regime_playbook.json'

    # Load data
    def load_json(f):
        if os.path.exists(f):
            with open(f, 'r') as j: return json.load(j)
        return None

    h1_data = load_json(h1_file)
    m30_data = load_json(m30_file)
    m15_data = load_json(m15_file)

    if not h1_data:
        print("Error: H1 baseline results not found.")
        return

    regimes = ["TREND_UP", "TREND_DOWN", "WEAK_UP", "WEAK_DOWN", "RANGE", "VOLATILE", "UNKNOWN"]
    timeframes = {"H1": h1_data, "M30": m30_data, "M15": m15_data}
    
    new_playbook = {
        "generated_at": datetime.now().isoformat(),
        "tp_mult": 1.5,
        "sl_mult": 1.0,
        "playbook": {},
        "regime_matrix": {}
    }

    # Build Matrix and find best for Playbook
    for reg in regimes:
        new_playbook["regime_matrix"][reg] = {}
        best_candidate = None
        max_score = -1e9

        for tf, data in timeframes.items():
            if not data: continue
            new_playbook["regime_matrix"][reg][tf] = {}
            
            # Use adaptive by_strategy if available (more refined), else use main strategies
            source = data.get('adaptive', {}).get('by_strategy', {})
            if not source:
                source = {name: s['stats'] for name, s in data.get('strategies', {}).items() if reg in s.get('regime_fit', [])}

            for sname, stats in source.items():
                pf = stats.get('pf', 0)
                wr = stats.get('wr', 0)
                n = stats.get('n', 0)
                pnl = stats.get('pnl', 0)
                
                # Scoring formula: PF * WR * (1 + log10(n)) to favor statistical significance
                import math
                score = pf * wr * (1 + math.log10(n) if n > 0 else 0)
                
                entry = {
                    "strategy": sname,
                    "n": n,
                    "wr": wr,
                    "pnl": pnl,
                    "pf": pf,
                    "dd": stats.get('dd', 0),
                    "score": round(score, 2)
                }
                
                new_playbook["regime_matrix"][reg][tf][sname] = entry
                
                # Update best candidate for playbook
                if score > max_score and n >= 10: # Minimum 10 trades for significance
                    max_score = score
                    best_candidate = {
                        "strategy": sname,
                        "tf": tf,
                        **entry
                    }

        if best_candidate:
            new_playbook["playbook"][reg] = best_candidate
        else:
            # Fallback
            new_playbook["playbook"][reg] = {"strategy": "S05_MFKK_INTRADAY", "tf": "H1", "pf": 1.0, "wr": 0}

    # Write output
    with open(out_file, 'w') as f:
        json.dump(new_playbook, f, indent=2)
    print(f"Successfully synced {out_file} with latest results.")

if __name__ == "__main__":
    sync()
