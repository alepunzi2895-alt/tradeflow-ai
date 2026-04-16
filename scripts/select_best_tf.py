import json, os

def load_res(path):
    if not os.path.exists(path): return None
    with open(path, 'r') as f: return json.load(f)

def run():
    h1 = load_res('results_h1.json')
    m30 = load_res('results_m30.json')
    m15 = load_res('results_m15.json')
    
    if not h1 or not m30 or not m15:
        print("Errore: alcuni file dei risultati non sono stati trovati.")
        return

    all_data = { 'H1': h1, 'M30': m30, 'M15': m15 }
    strategies = h1['strategies'].keys()
    
    report = {}
    
    print(f"{'Strategia':<22} | {'Best TF':<7} | {'PF':>6} | {'WR%':>6} | {'N':>5}")
    print("-" * 60)
    
    for s_name in strategies:
        best_tf = None
        best_score = -1
        best_stats = None
        
        for tf, bundle in all_data.items():
            s_data = bundle['strategies'].get(s_name)
            if not s_data: continue
            
            stats = s_data['stats']
            pf = stats['pf']
            wr = stats['wr']
            n = stats['n']
            
            # Score logic: penalize very low trade counts, reward WR and PF
            # We want at least 40 trades in 2 years for statistical significance
            if n < 30: PF_adj = pf * 0.5
            else: PF_adj = pf
            
            score = PF_adj * (wr / 100) * (n ** 0.3)
            
            if score > best_score:
                best_score = score
                best_tf = tf
                best_stats = stats
        
        report[s_name] = { 'best_tf': best_tf, 'stats': best_stats }
        s = best_stats
        print(f"{s_name:<22} | {best_tf:<7} | {s['pf']:>6.3f} | {s['wr']:>6.1f} | {s['n']:>5}")

    with open('best_tf_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    print("\nReport salvato in best_tf_report.json")

if __name__ == "__main__":
    run()
