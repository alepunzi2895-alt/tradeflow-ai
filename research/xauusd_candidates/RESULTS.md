# Ricerca strategia XAU/USD — indicatori nativi TradingView

**Obiettivo**: trovare una strategia il più possibile robusta/a basso rischio su OANDA:XAUUSD H4, usando la libreria indicatori nativa completa di TradingView (fuori dal set già usato dalle 5 strategie attive del progetto: Ichimoku, Supertrend nativo, Parabolic SAR, Keltner Channel, Chaikin Money Flow — non ADX/DI custom, MACD, CCI stocastico, EMA stack, OBV, FVG/OB già in uso).

**Metodologia**: 5 candidati testati su OANDA:XAUUSD H4 (~6.5 anni di storico, 2020-01-01 → 2026-07-17). TP/SL ATR-based uniformi (TP 2.5×ATR, SL 1.2×ATR, R:R≈2.08) per confronto equo, un trade alla volta, quantità fissa, commissioni/slippage a zero (limite dei dati disponibili, non modellati). Split temporale IS (80%, 2020-01-01→2025-03-01) / OOS (20%, 2025-03-01→2026-07-17) tramite filtro `time` in Pine (il date-range picker nativo dello Strategy Tester è a pagamento — Premium — sull'account usato, non disponibile).

**Nota di contesto importante**: l'oro è stato in un forte trend rialzista nella finestra OOS (2025-03→2026-07). Tutti e 4 i candidati trend-following testati mostrano OOS sistematicamente più forte dell'IS — pattern coerente con un effetto di regime di mercato favorevole, non necessariamente con un edge specifico di ciascuna strategia. Questo va tenuto presente: i numeri OOS da soli sono probabilmente ottimistici rispetto a quello che succederebbe in un mercato laterale o ribassista.

## Candidati testati

| # | Nome | Logica | IS n / WR / PF / DD% | OOS n / WR / PF / DD% | Full PF | Verdetto |
|---|---|---|---|---|---|---|
| C1 | EMA200 + RSI(14) pullback | Trend EMA200, ingresso su RSI che rientra da 40/60 | — (scartato prima) | — | 1.004 | ❌ Scartato — full-period sostanzialmente breakeven, non degno di split IS/OOS |
| C2 | Ichimoku Kumo + Tenkan/Kijun cross | Prezzo sopra/sotto la nuvola, ingresso su incrocio Tenkan/Kijun | 149 / 34.9% / 1.094 / 1.27% | 32 / 46.9% / 1.572 / 1.70% | 1.298 | ⚠️ Passa la soglia PF ma campione OOS sottile (n=32) e IS solo marginalmente profittevole |
| C3 | Supertrend(10,3) nativo + ADX(14)>25 | Flip Supertrend filtrato da forza del trend (ADX) | 68 / 35.3% / 1.046 / 1.97% | 21 / 42.9% / 1.995 / 1.16% | 1.423 | ❌ Scartato — campione OOS troppo piccolo (n=21, sotto la soglia minima 30) per fidarsi del PF alto |
| **C4** | **Keltner Channel(20,2×ATR10) breakout + Chaikin Money Flow(20)** | **Breakout dal canale confermato da denaro in ingresso (CMF stesso segno)** | **254 / 36.2% / 1.123 / 2.54%** | **65 / 49.2% / 1.767 / 1.98%** | **1.375** | **✅ Promosso — miglior combinazione di campione (il più ampio in entrambe le finestre), PF>1 in entrambe le finestre, drawdown moderato e stabile** |
| C5 | Parabolic SAR(0.02/0.02/0.2) flip + MACD histogram | Flip SAR confermato da istogramma MACD stesso segno | 320 / 31.6% / **0.982** / 4.88% | 71 / 45.1% / 2.179 / 2.79% | 1.389 | ❌ Scartato — **PF IS < 1 (perdente su 80% dello storico)**, tutta la profittabilità full-period viene dalla finestra OOS/trend recente. Il caso più chiaro di "regime, non edge" tra i 5 |

## Candidato promosso: C4 — Keltner Channel breakout + Chaikin Money Flow

**Logica**: canale di Keltner (EMA20 ± 2×ATR10); ingresso long quando la chiusura rompe sopra il canale superiore E il Chaikin Money Flow(20) è positivo (conferma pressione di acquisto); speculare per lo short. TP 2.5×ATR / SL 1.2×ATR.

**Perché è il più "sicuro" tra i 5**:
- Campione più ampio in assoluto sia IS (254 trade) sia OOS (65 trade) — il verdetto statistico è il più affidabile del gruppo, non un artefatto di pochi trade fortunati.
- Profit Factor > 1 in ENTRAMBE le finestre temporali (1.123 IS, 1.767 OOS) — a differenza di C5, non è mai stato un perdente netto nemmeno nel periodo meno favorevole.
- Drawdown moderato e consistente tra le due finestre (2.54% IS, 1.98% OOS) — nessun salto verso l'alto tipico di un edge fragile che collassa fuori campione.

**Ma, onestamente**: il margine IS (PF 1.123) è sottile — un edge reale ma modesto, non un vantaggio enorme. Buona parte del rendimento cumulato (P&L 24m +13.85% full-period) è comunque concentrata nel recente trend rialzista dell'oro, non distribuita uniformemente. Aspettarsi risultati futuri più vicini alla media tra IS e OOS (PF realistico stimato ≈1.2-1.4) piuttosto che al PF OOS isolato (1.767) è la lettura prudente. Nessuna strategia testata è "sicura" in senso assoluto: tutte restano sistemi probabilistici con drawdown reali (qui, storicamente, fino a ~2.5% del capitale nella finestra peggiore) e nessuna garanzia che il pattern osservato regga in condizioni di mercato future diverse (es. oro laterale/ribassista, mai attraversato nella finestra OOS testata).

**Non promosso al roster live**: nessuna modifica a `scripts/signals.py` o ad altri file del bot — è pura ricerca esplorativa, da valutare esplicitamente con l'utente prima di qualunque integrazione (serve almeno: validazione su un secondo TF, stima costi di transazione reali, e idealmente un periodo di paper trading, come da prassi già consolidata in questo progetto).

## Validazione aggiuntiva C4 (richiesta esplicita utente prima di considerare paper trading)

Tre verifiche di robustezza, stesso script C4 invariato (Keltner(20,2×ATR10) breakout + CMF(20), TP2.5×ATR/SL1.2×ATR), stesso simbolo OANDA:XAUUSD.

### 1. Secondo timeframe — H1

Dati H1 disponibili solo da 2024-01-02 (molto meno storico di H4). Stesso split cronologico IS(fino 2025-03-01)/OOS(dopo):

| Finestra | Trade | WR | PF | DD% |
|---|---|---|---|---|
| IS (2024-01→2025-03) | 227 | 29.07% | **0.832** | 3.64% |
| OOS (2025-03→2026-07) | 253 | 37.15% | 1.086 | 5.62% |

**Non regge.** Su H1 la strategia è nettamente perdente nella finestra più vecchia (PF 0.832, quasi il doppio dei trade in perdita rispetto a quelli in guadagno) e solo marginalmente positiva in quella recente. L'edge osservato su H4 non si trasferisce a un timeframe diverso — segnale classico di un pattern specifico del TF/periodo testato, non di un vantaggio strutturale della logica Keltner+CMF.

### 2. Costi di transazione realistici (H4)

Stesso test H4 IS/OOS originale, aggiunto `slippage=35` in Pine (~$0.35 per ordine, applicato sia in entrata che in uscita — quindi un costo round-trip approssimativamente doppio rispetto a un singolo spread pagato una volta, stima prudenziale):

| Finestra | PF senza spread | PF con spread ~$0.35×2 | Erosione |
|---|---|---|---|
| IS | 1.123 | 1.12 | trascurabile |
| OOS | 1.767 | 1.766 | trascurabile |

**Costi non sono il problema.** Su H4 le escursioni ATR-scaled (TP/SL nell'ordine di decine di dollari) rendono un costo di ~$0.70 per trade irrilevante in proporzione. Questo NON salva la strategia dagli altri due problemi trovati — significa solo che, se l'edge fosse reale, i costi di esecuzione non lo ucciderebbero.

### 3. Finestra di mercato non-trending (H4, 2021-01 → 2022-09)

Periodo storico noto di consolidamento/correzione dell'oro (dopo il massimo storico di ago-2020, prima della fase di forte rialzo del 2023+) — non confermato via scroll interattivo del grafico (limite del data feed sull'account usato per la vista live, il motore di backtest invece processa comunque tutto lo storico), scelto sulla base di storico prezzi oro ben documentato pubblicamente:

| Finestra | Trade | WR | PF | P&L |
|---|---|---|---|---|
| 2021-01 → 2022-09 | 82 | 34.15% | **1.022** | +$14.97 (+0.15%) |

**Sostanzialmente breakeven.** In un regime non chiaramente direzionale, C4 non genera un vantaggio reale — conferma diretta che l'edge misurato altrove dipende dal contesto di trend, non da un vantaggio strutturale della logica breakout+money-flow.

### Verdetto finale

**C4 non regge la validazione aggiuntiva — non è pronto nemmeno per un paper trading serio così com'è.** Tre segnali coerenti puntano nella stessa direzione: (1) non generalizza a un altro timeframe (perdente su H1 IS), (2) è breakeven in un regime di mercato non-trending (2021-2022), (3) la sua forza è quasi interamente confinata a finestre H4 in trend rialzista pulito — la stessa dinamica di "regime, non edge" già isolata e scartata esplicitamente per C5 nella tabella comparativa sopra. I costi di transazione non sono il fattore limitante (punto 2), quindi non è nemmeno un problema risolvibile ottimizzando l'esecuzione.

Se in futuro si vuole recuperare l'idea, andrebbe riformulata esplicitamente come filtro di regime ("solo quando ADX H4 conferma trend forte", nello stile già usato dalle strategie attive del progetto) piuttosto che come sistema standalone always-on — ma a quel punto è un lavoro di design nuovo, non una conferma di questo candidato.
