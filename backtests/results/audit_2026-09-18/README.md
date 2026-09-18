# Confronto strategie — simulazione corretta

Nessuna nuova promozione sul conto reale. Il requisito statistico non è soddisfatto da nessuna delle nove strategie.

| Strategia | PF intero periodo | Trade recenti | PF recente | DD recente (unità del simulatore) | Esito |
|---|---:|---:|---:|---:|---|
| S00_MFKK | 1.238 | 244 | 1.314 | 599.4 | dsr |
| S09_MFKK_SCALPING | 0.902 | 22 | 1.854 | 79.8 | sample, positive_segments, dsr |
| S10_OB_FVG_SCALP | 1.534 | 7 | 6.599 | 18.6 | sample, dsr |
| S16_GOLDEN_SQUEEZE | 1.877 | 35 | 1.430 | 279.3 | dsr |
| S17_CONVERGENCE_SCALP | 2.344 | 19 | 1.770 | 194.3 | sample, dsr |
| S18_RANGE_REVERSAL | 0.740 | 35 | 0.376 | 241.5 | holdout_pf, holdout_positive, positive_segments, extra_costs, dsr |
| S20_FIB_CONFLUENCE | 1.718 | 14 | 0.861 | 21.3 | sample, holdout_pf, holdout_positive, extra_costs, dsr |
| S31_LAYOUT_SMART | 1.966 | 9 | 1.624 | 130.4 | sample, dsr |
| S30_DOW_DIP | 1.101 | 23 | 1.144 | 1631.8 | sample, holdout_pf, positive_segments, dsr |

## Priorità di approfondimento

1. **S17 Convergence**: PF recente 1,77, 19 trade. Primo candidato per validazione forward demo, campione ancora insufficiente.
2. **S31 Layout Smart**: PF recente 1,624, 9 trade. Campione molto piccolo; secondo candidato demo.
3. **S00 e S16**: migliorano con il simulatore corretto, ma non superano il controllo DSR; i blocchi live restano validi, incluse le ragioni derivanti dai trade reali.
4. **S30 Dow Dip**: dopo il time-stop e il vincolo di una sola posizione il PF recente scende a 1,144. Necessita revisione, non aumento di esposizione.
5. **S18 e S20**: PF recente inferiore a 1; nessuna riattivazione.

## Metodo e limiti

Registro cumulativo: 1753 valutazioni. Configurazioni congelate, nessun tuning per massimizzare questo report. Ultimo 20% del tempo come finestra recente, sette giorni di esclusione al confine, quattro segmenti cronologici precedenti. Il DSR usa anche i giorni feriali senza trade e il conteggio cumulativo dei tentativi.

Gli importi XAU e US30 sono espressi nelle unità proprie del simulatore, **non sono sommabili come denaro del conto**. La penalità aggiuntiva di costo è uno stress descrittivo (1 unità XAU, 3 punti US30 per trade), non un replay di tick del broker.

I dati erano già stati utilizzati in ricerca. Il confronto cronologico non costituisce una nuova prova fuori campione. Occorre osservazione demo successiva al congelamento dei parametri, con contratto, spread, sizing e gestione delle posizioni effettivi. Non esiste ancora evidenza sufficiente per dichiarare equivalenza con i nuovi controlli di esecuzione live.

La selezione serve a stabilire cosa approfondire; non è una promessa di rendimento.

Per ogni dataset e file Python utilizzato, `report.json` contiene SHA-256, date e versione del codice. I nove file per strategia contengono i trade simulati. `legacy-diagnostic.json` documenta i risultati prima della correzione del simulatore.
