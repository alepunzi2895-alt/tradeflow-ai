# Audit, verifica e rilascio — 18 settembre 2026

## Stato

Correzioni e backtest verificati localmente. Nessun ordine inviato e nessuna nuova
strategia promossa sul conto. Il rilascio coordinato di API, bot e worker richiede
la configurazione descritta sotto: il semplice push della nuova API non aggiorna
il processo Python sulla VPS.

## Correzioni

| Area | Comportamento verificato |
|---|---|
| Autenticazione | JWT senza segreti di fallback, cookie HttpOnly/SameSite, migrazione dei bearer esistenti, namespace utente imposto dal server |
| Operatore | Controlli di trading riservati agli ID immutabili in `ADMIN_USER_IDS`; lettura del conto anche agli ID esplicitamente autorizzati in `system_readers`, identità del bot separata |
| Reset password e ordini manuali | Vecchie azioni remote restituite come 410: permettevano bypass dei controlli |
| AI | Autenticazione, quota persistente per utente, modello e token limitati dal server, timeout |
| Journal | Eliminazione con ownership, importazione MyFxBook atomica e idempotente, provenienza conservata, errori di sync visibili |
| KB/MyFxBook | Routing corretto; KB personale in Turso; password MyFxBook solo in memoria; testo AI e campi importati escapati |
| Backtest remoto | Richieste separate con UUID, lease atomica, tre tentativi, risultati associati a utente e richiesta |
| Bot | Niente riattivazione automatica al boot; stato sconosciuto/scaduto blocca i nuovi ingressi; verifica TLS abilitata |
| Sizing | Arrotondamento per difetto, rifiuto del minimo fuori budget, conversione del contratto tramite MT5 nella valuta del conto |
| Rischio finale | 2% per ingresso, 4% complessivo, riserva costi 10%, massimo tre posizioni sul conto; circuito giornaliero 3% e settimanale 6%, inclusi trade manuali |
| Registro strategie | API, bot e Saturno leggono lo stesso registro e gli hard block; distinzione tra configurazione salvata e confermata dal bot |
| Laboratorio | Worker separato, dataset con SHA-256, protezione da risultati riferiti a selezioni cambiate, Donchian sulle barre precedenti |
| Obsidian | Aggiornamento dei soli blocchi generati; note legacy conservate e file companion; token personale obbligatorio |
| Dipendenze/verifiche | Lock npm aggiornato, dipendenze Python riproducibili, controlli automatici e test browser con fixture locali |

Le percentuali del guardiano finale sono tetti nominali: gap e slippage possono
superare lo stop. Questa modifica rende più restrittivo il comportamento del bot;
va verificata su demo prima di riavviare un conto reale.

## Backtest corretti

Il vecchio simulatore applicava stop ricavati dalla chiusura della barra ai massimi
e minimi della stessa barra. La simulazione ora controlla prima gli ordini già in
essere e applica il nuovo trailing alla barra successiva. Sono incluse uscite a
scadenza e gap sullo stop. Il simulatore US30 evita posizioni sovrapposte e usa il
time-stop di 18 barre della strategia live. La gestione strutturale S31 controlla
lo stop originario prima di contabilizzare target parziali.

Risultati e file di provenienza: `backtests/results/audit_2026-09-18/`.
`legacy-diagnostic.json` conserva il primo confronto, precedente alle correzioni;
`report.json` è il confronto aggiornato. I dati storici erano già stati usati nella
ricerca: nessun risultato viene presentato come prova indipendente su dati nuovi.

## Prima del rilascio

1. Configurare in Vercel `JWT_SECRET` casuale di almeno 32 caratteri e
   `ADMIN_USER_IDS` con gli ID degli operatori autorizzati. La configurazione
   remota non è verificata da questo checkout, che non è collegato alla CLI Vercel.
2. Verificare `MT5_BOT_SECRET` identico su Vercel, bot, manutenzione e worker.
   Configurare `TV_WEBHOOK_SECRET` anche negli alert TradingView.
3. Conservare le note Obsidian esistenti e configurare `OBSIDIAN_AUTH_TOKEN` con
   un token dell'utente proprietario; non usare il segreto del bot per il Journal.
4. Aggiornare API e processi Python insieme. Il vecchio worker non invia i nuovi
   request/lease ID; le vecchie letture anonime del bot vengono respinte.
5. Verificare su demo login, stato bot, import, quota AI, lease del worker e rifiuto
   dei lotti fuori budget. Solo l'operatore può riabilitare gli ingressi.

Il rilascio del 18 settembre ha evidenziato due requisiti di configurazione: il
segreto JWT valido e il permesso esplicito di lettura del conto. Il login remoto
ora funziona; il gateway restituisce 503 anche sul controllo di salute quando il
segreto è assente o troppo corto. Nessun processo VPS è stato riavviato.

### Ripristino dashboard

L'account indicato dal proprietario è stato autenticato e abilitato alla sola
lettura dei dati MT5 tramite `system_readers`. Non sono stati assegnati permessi
di trading. Per abilitare un altro proprietario verificato:
`node scripts/grant-system-read.mjs --user-id <verified account ID>`.
Il comando richiede accesso amministrativo locale a Turso; nessuna API pubblica
può auto-assegnare il permesso. Il grant è separato da `user_data`.

La dashboard mostra equity, P&L giornaliero UTC, P&L aperto e WR/PF calcolati sui
trade chiusi ricevuti, con numerosità e orario di sincronizzazione espliciti.
Un errore 401/403 elimina i dati del conto dalla vista. Le quotazioni hanno una
sola sezione e un unico ciclo batch a 5 secondi; i dati MT5 si aggiornano ogni 20.

## Limiti residui espliciti

- Le letture di mercato dipendono dai provider: i test con fixture verificano il
  contratto applicativo, non disponibilità o puntualità dei feed in produzione.
- Il Laboratorio visuale resta un simulatore di ricerca: non include la gestione
  completa del broker e non promuove automaticamente le regole al bot.
- Il Journal può lavorare con dati locali, ma non ha una coda offline completa di
  mutazioni e conflitti fra dispositivi. Errori di salvataggio vengono mostrati.
- I salvataggi per-utente sono blob last-write-wins; modifiche contemporanee da
  due dispositivi richiedono una futura revisione della sincronizzazione.
- I vecchi import duplicati privi di provenienza non vengono cancellati a intuito.
- Le vecchie metriche statiche nella UI sono etichettate come baseline precedente;
  il nuovo confronto è nel report, non è stato pubblicato automaticamente in Turso.

## Comandi di verifica

```text
npm ci
pip install -r requirements.txt
npm test
python scripts/test_execution_safety.py
python scripts/check_config_consistency.py
npx playwright install chromium
npm run test:ui
python -X utf8 scripts/research_audit.py
```

L'ultimo comando registra una nuova sessione di nove valutazioni. Non lanciarlo
per una semplice verifica della UI; non invia risultati al cloud e non apre ordini.
