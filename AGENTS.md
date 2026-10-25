# AGENTS.md

## Obiettivo del progetto

DailyCulture è un sistema automatico che genera articoli culturali quotidiani, li invia su Telegram e li archivia nel repository in formato Markdown. L’obiettivo attuale è preservare questo flusso esistente e preparare il repository a una futura web app senza duplicare la logica di generazione.

Il codice principale è `culture_agent.py`, mentre il workflow di produzione è `.github/workflows/daily.yml`.

## Architettura reale

### Flusso attuale

1. GitHub Actions avvia il workflow `.github/workflows/daily.yml` a orari schedulati.
2. Il job esegue `python culture_agent.py` con le variabili di ambiente da GitHub Secrets.
3. `culture_agent.py`:
   - legge e aggiorna `history.json`;
   - decide se oggi è il giorno giusto per inviare (`should_send`);
   - genera contenuti con Gemini (eventualmente con ricerca web);
   - invia i messaggi su Telegram;
   - salva la cronologia e i singoli articoli in `archivio/`.
4. Un step successivo del workflow esegue `git add -A`, `git commit` e `git push` per aggiornare il repository.

### File chiave

- `culture_agent.py`: legge `history.json`, genera contenuti, chiama Gemini, invia Telegram e archivia.
- `history.json`: stato del sistema, ultimo invio e log degli articoli.
- `archivio/YYYY/YYYY-MM-DD.md`: archivio giornaliero in Markdown.
- `archivio/settimane/YYYY-Wxx.md`: riepilogo settimanale.
- `.github/workflows/daily.yml`: workflow attualmente in uso.

## Struttura delle directory

- `archivio/2026/` : file giornalieri di archivio per anno e data.
- `archivio/settimane/` : riepiloghi settimanali.
- `.github/workflows/` : automazioni GitHub Actions.
- `tests/` : test unitari, se aggiunti.

## Formato dei dati e convenzioni

### `history.json`

Il file attuale contiene uno stato di tipo JSON con:

- `_last_sent`: data ISO dell’ultimo invio
- `_offset`: offset Telegram usato per leggere feedback
- `log`: array di voci generate
- `ratings`: mappatura dei voti ricevuti da Telegram

Ogni voce `log` ha forma reale come:

```json
{
  "id": "20261023-art",
  "date": "2026-10-23",
  "cat": "arte",
  "key": "Autore - Titolo",
  "title": "Titolo dell'articolo",
  "recap": "Breve riassunto"
}
```

Convenzioni effettive usate nel codice:

- `id`: identificativo stabile nel formato `YYYYMMDD-<categoria-id>`
- `date`: data ISO `YYYY-MM-DD`
- `cat`: categoria del contenuto (`letteratura`, `storia`, `musica`, ecc.)
- `key`: chiave di pagina/articolo
- `title`: titolo mostrato a Telegram
- `recap`: riassunto breve usato in quiz e nel catalogo

Questa convenzione è già adatta a una futura web app, perché identifica ogni articolo in modo stabile senza dover rigenerarlo.

### `archivio/*.md`

I file giornalieri sono l’archivio persistente degli articoli. La convenzione attuale è:

- path: `archivio/YYYY/YYYY-MM-DD.md`
- titolo iniziale: `# <giorno e data>`
- contenuto testuale con sezioni per categoria
- file settimanali in `archivio/settimane/YYYY-Wxx.md`

Questo è il formato più semplice e compatibile per una future web app in lettura.

## Regole per evitare duplicazioni e perdita di dati

- Non modificare il workflow principale in `.github/workflows/daily.yml` senza giustificazione chiara.
- Non cambiare la convenzione `id` senza aggiornare compatibilità e cronologia.
- Non usare un nome derivato dal titolo come chiave principale dell’articolo.
- Prima di aggiungere una voce nuova, verificare che non esista già un `id` con la stessa data/categoria.
- Il codice usa `state["log"]` e `_last_sent` to prevenire doppie pubblicazioni.
- Non eliminare o rinominare file in `archivio/` senza comprendere le dipendenze.
- Non sovrascrivere `history.json` senza verificare temporaneamente il contenuto già esistente.

## Installazione e test

### Dipendenze

Il repo attuale usa Python 3.12 e una dipendenza minima:

```bash
python -m pip install requests
```

Non esiste `requirements.txt` nel repo reale analizzato.

### Test disponibili

Non ci sono test predefiniti nel repository attuale. I nuovi test aggiunti devono essere leggeri e non richiedere segreti o chiamate reali a Gemini o Telegram.

Esempio di comando per test locali:

```bash
python -m unittest discover -s tests -v
```

## File sicuri da modificare

File di documentazione e test sono corretti da toccare senza rischio:

- `AGENTS.md`
- `docs/`
- `tests/`

File critici e da toccare con cautela:

- `culture_agent.py`
- `history.json`
- `archivio/`
- `.github/workflows/daily.yml`

## Segreti e variabili d'ambiente

Le variabili di ambiente / secret usati dal workflow sono (realmente presenti nel workflow):

- `GEMINI_API_KEY`
- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`
- `FORCE` (solo con `workflow_dispatch`)

Non stampare, copiare o inserire valori reali in file o log. Non usare `print` per segreti. Non aggiungere nuovi secret senza necessità dimostrata.

## Convenzioni per branch, commit e PR

- Lavorare sempre su branch dedicato, non su `main`.
- I commit devono essere descrittivi, ad esempio:
  - `docs: add repository architecture guide`
  - `test: add state deduplication checks`
- In PR, descrivere:
  - cosa cambia;
  - perché resta compatibile;
  - se tocca `history.json`, `archivio/` o workflow.

## Compatibilità futura

- Non introdurre database o servizi a pagamento in questa fase.
- Preferire contenuti versionati nel repository come sorgente di verità.
- La futura web app deve leggere `archivio/YYYY/YYYY-MM-DD.md` e `history.json`, senza rigenerare gli articoli.
- Il flusso Telegram deve restare invariato.
- Eventuali nuovi file per il web devono essere compatibili con il modello attuale e non distruggere la cronologia.

## Preparazione per la future web app

La strategia più semplice e robusta è:

1. usare `history.json` come indice dei metadati;
2. usare `archivio/YYYY/*.md` come contenuto giornaliero;
3. usare `archivio/settimane/*.md` come vista settimanale;
4. mettere una pagina web successiva sopra questi file senza duplicare la logica di generazione.

Non addizionare ancora endpoint pubblici, webhooks, database o push browser.

## Sicurezza di repository

- Non pubblicare dati privati.
- Non disattivare protezioni di GitHub Actions.
- Non rendere pubblico il repository senza esplicita richiesta.
- Non eseguire operazioni distruttive sui file di archivio e sulla cronologia.

## Conclusione

L’architettura attuale è semplice, stabile e compatibile: GitHub Actions + Python + Gemini + Telegram + archivio file-based. Il repository deve essere preparato come fonte di verità per una futura web app, senza cambiare il comportamento attuale di produzione.
