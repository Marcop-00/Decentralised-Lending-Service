# Correzioni successive alla verifica dell'11 ottobre 2026

Questo documento aggiorna gli esiti del rapporto iniziale conservato in
`verifica_progetto_2026-10-11/rapporto.md` nella cartella del corso. Quel rapporto
descrive il codice precedente alle correzioni.

## Stato dei problemi identificati

| Rilievo | Correzione | Stato |
|---|---|---|
| R01 — Snapshot incompleto/errori ignorati | Genesis mainnet noto, catena continua di 131.000 blocchi, validazione hash/Merkle, blocchi applicati atomicamente e stato azzerato dopo errori. CLI offline `python/oracle/check_data.py`. | **Risolto**: nuovi dati verificati con replay completo dei 131.000 blocchi richiesti. |
| R02 — Premio genesis conteggiato | Il blocco zero è incluso nel conteggio ma i suoi output non entrano negli UTXO; successivi pagamenti allo stesso indirizzo restano validi. | Corretto e testato. |
| R03 — Eventi persi | Inbox/outbox SQLite, cursore atomico, ripresa da deploy, transazioni firmate persistite prima dell'invio, verifica receipt, retry, checkpoint del blocco e segnalazione dei conflitti di nonce. | Corretto e testato con RPC simulato. |
| R04 — Contributor interamente locked escluso dal voto | Idoneità dalla posizione totale; voto anche a peso zero, peso ricalcolato sul disposable alla risoluzione. | Corretto e testato. |
| R05 — Gas incompleto/gasLimit scambiato per costo | Misure `gasUsed` di 20 scenari, test sul costo effettivo, fee oracolo verificata rispetto alla misura. Coverage separata dai dati gas. | Profilazione eseguita su EVM Berlin. |
| R06 — Reentrancy dimostrata solo su esempio estraneo | Variante vulnerabile del vero FundingPool con scritture obsolete dopo la call; stesso attacker su proxy sicuro e vulnerabile. | Attacco riuscito solo sulla variante vulnerabile. |
| R07 — Setup/demo poco robusti | Controlli chain/receipt/bytecode, account prefunded usato solo per trasferimenti, proposta identificata dall'evento, saldo oracle fresco e voto YES effettivo. Ricompilazione normale prima di qualsiasi deploy. | Test offline e **demo completa su Geth 1.13.14 superati**. |

## Allineamento al laboratorio e interpretazioni

- Hardhat 3.18.1, TypeScript 6.0.3, node:test e viem; eliminati configurazione e
  test JavaScript. Aggiunti test Solidity nativi, incluso fuzzing della conservazione
  dei rimborsi. Dipendenze fissate nel lockfile e OpenZeppelin dichiarato direttamente;
  rimosse le vecchie copie semplificate inutilizzate in `vendor/`.
- A01: ogni rata è ripartita proporzionalmente tra capitale e interesse con obiettivi
  cumulativi; anche il collateral usa arrotondamenti cumulativi. Le eccedenze oltre
  l'intero debito alimentano la compensation pool.
- A02: 12 blocchi sono il minimo prima della risoluzione, con voto aperto fino alla
  chiusura effettiva della proposta.
- A03: una richiesta valida con compensation pool vuota registra il default,
  paga zero e mantiene il credito per un tentativo successivo.
- Queste tre regole sono interpretazioni documentate delle parti meno esplicite
  della traccia, non chiarimenti ricevuti dal professore.
- Rimossi i contributor con posizione vuota; ordine dei rimborsi ordinato e
  memorizzato una sola volta per prestito. Nuovi eventi per osservare le transizioni.
- Test di upgrade a V2 compatibile con verifica di stato, posizioni e proprietario.
  Gli upgrade della pool non cambiano il bytecode dei LoanContract già creati.

## Verifiche effettuate

- TypeScript strict: `npm run typecheck`.
- Hardhat: **32 test superati**, 28 TypeScript e 4 Solidity; il test fuzz esegue
  256 casi. Anche l'esecuzione con coverage supera tutti i test.
- Python: **43 test superati**, offline e senza chiavi reali o connessioni RPC.
- Coverage Hardhat: **84,75% righe**, **86,15% statement** complessivi sui file
  riportati (inclusi i contratti ausiliari); HTML in `coverage/html/`.
- `npm run test:gas`: 20 scenari in `gas-measurements.json`; prima scrittura
  nonzero dell'oracolo, indirizzo di 34 caratteri: **49.426 gas**, fee a 0,1 gwei
  pari a **4.942.600.000.000 wei**. Non è un limite superiore universale.
- Relazione `report.pdf` compilata e controllata visivamente, quattro pagine.

La copertura e i test non equivalgono a una prova generale di sicurezza. La rete
dei test è simulata, configurata come il genesis del corso per chain ID e Berlin.

## Nuovi dati Bitcoin verificati

Dopo la sostituzione dei `.dat` da parte dell'utente, l'11 ottobre 2026, entrambe
le cartelle `bitcoin/` contengono sette file, da `blk00000.dat` a `blk00006.dat`,
con dimensioni e SHA256 identici. Totale per copia: 939.421.031 byte.

La scansione rileva 163.723 record e una catena connessa di **162.844 blocchi**.
Il replay ha elaborato esattamente i primi **131.000 blocchi**, altezze 0–130.999,
con controllo hash/Merkle superato, ricostruendo **299.208 UTXO** e **153.986
voci di indirizzo**. Esito `valid: true`, exit code 0; risultato salvato in
`bitcoin-validation.json`. Il saldo dell'indirizzo genesis nello snapshot è
4.000.000 satoshi (0,04 BTC), senza includere il premio originario di 50 BTC.

Il precedente impedimento dei dati incompleti è quindi risolto. Comando di verifica:

```sh
./.venv/bin/python python/oracle/check_data.py --data-dir bitcoin --summary
```

## Demo completa verificata su Geth

L'11 ottobre 2026, alle 17:48, il percorso `setup → oracle/voter → simulate` è
terminato correttamente su Geth **1.13.14**, chain ID **202526**, genesis del corso
invariato e periodo Clique di **10 secondi**. La prova ha usato una nuova chain
locale su porta 18545, senza peer P2P, e gas price di **0,1 gwei**. Le copie dei
23 file sorgente/configurazione usati sono state confrontate con SHA256.

- Account prefunded usato esclusivamente per tre trasferimenti ai nuovi account.
- **15 ricevute di transazione con status 1**, inclusi deploy, richiesta/risposta
  dell'oracolo, deposito, proposta, voto, risoluzione, due rate e incasso interessi.
- **20 controlli finali sullo stato superati**, più verifica degli eventi delle rate.
- Entrambe le code SQLite hanno un evento completato e nessun evento pending/dead.
- Prestito: **1 ETH al 5%**, rimborsato con **due rate da 0,525 ETH**.
- Capitale disponibile finale: **50 ETH**; locked **0**; prestiti attivi **0**;
  stato del Loan **Repaid**; interessi da riscuotere **0**.
- Guadagno lordo incassato: **0,025 ETH**; compensation pool: **0,025 ETH**;
  saldo complessivo della pool: **50,025 ETH**.
- Collateral globale finale **45%**, snapshot del prestito **50%**.

Le ricevute, gli indirizzi di test, lo stato e gli hash dei sorgenti sono salvati
in `geth-demo.json`. I processi temporanei sono stati fermati. La chain e le
configurazioni del deployment preesistente non sono state modificate.

## Preparazione della consegna

Il controllo dei dati e la demo Geth sono ora completati. Resta la preparazione
dello ZIP secondo il README e le regole del corso. Le interpretazioni A01–A03
rimangono documentate come scelte implementative, non come chiarimenti del docente.
