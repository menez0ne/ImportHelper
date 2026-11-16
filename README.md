# ImportHelper

Raccoglie da tutta Europa gli annunci delle auto che cerchi, li salva in un database locale,
converte i prezzi in euro con i cambi BCE e li mostra in un sito con le notifiche.

## Installazione (Windows, 5 minuti, una volta sola)

1. **Scarica** ImportHelper: in alto nella pagina GitHub premi il pulsante verde **Code**, poi
   **Download ZIP** (oppure usa lo ZIP che ti hanno mandato).
2. **Estrai** lo ZIP: tasto destro sul file, **Estrai tutto...**, e scegli una cartella dove
   resterà per sempre, per esempio `Documenti\ImportHelper`. Non lasciarla in Download
   e non spostarla dopo (se la sposti, rifai il punto 3).
3. Nella cartella estratta fai **doppio clic su `installa.bat`**.
   - Se compare "Windows ha protetto il PC": clicca **Ulteriori informazioni**, poi **Esegui comunque**.
   - Se Python non c'è, l'installazione lo scarica e lo installa da sola (se Windows chiede
     conferma rispondi **Sì**).
4. Alla fine si apre il sito e sul Desktop trovi l'icona **ImportHelper**. Fatto.

Si parte senza ricerche: nel sito apri **Cerca un'auto**, scrivi l'auto che ti interessa e
salva la ricerca. Le ricerche salvate si aggiornano da sole ogni 3 ore.

Se qualcosa va storto, rifai doppio clic su `installa.bat`: rifà solo quello che manca.
Per togliere tutto: doppio clic su `disinstalla.bat`, riavvia il PC e cancella la cartella.

**Nota**: il PC deve essere acceso perché la raccolta giri. Tutto resta sul tuo PC
(cartella `data`): nessun account, nessun dato inviato a nessuno.

## Come si usa (ogni giorno)

Apri **ImportHelper** dal Desktop o dal menu Start: si apre il sito (http://localhost:8765)
con gli annunci. L'icona accende da sola il piccolo server del sito, senza finestre.

Le ricerche salvate si aggiornano da sole **ogni 3 ore** e **5 minuti dopo l'accesso a
Windows**, in background. Se il PC era spento all'ora prevista, la raccolta parte appena
possibile. Il sito, se è aperto, si ricarica da solo ogni 15 minuti.

**Segnalibro nel browser** (http://localhost:8765): funziona quando il server del sito è acceso.
Senza altro, si accende cliccando l'icona e resta acceso fino allo spegnimento del PC.
Perché parta da solo a ogni accesso a Windows: doppio clic **una volta** su
`avvio-automatico-server.bat` (mette un collegamento nascosto in "Esecuzione automatica" e
accende subito il server). Per toglierlo: `disattiva-avvio-automatico-server.bat`.

Il resoconto dell'ultima raccolta è in `data\ultimo_giro.log` (o `data\server.log` se il
server era acceso). Per una raccolta subito, a mano: doppio clic su `avvia.bat`.

## Cercare qualsiasi auto (sezione "Cerca un'auto")

1. Nel sito apri **Cerca un'auto**, scrivi marca e modello (con i suggerimenti presi da
   AutoScout24), se vuoi gli anni, le parole che devono esserci (es. `gt3`, `plaid`), quelle
   da escludere e il prezzo minimo.
2. Scegli se **salvare** la ricerca, poi **Cerca su tutti i siti**: vedi sito per sito a che
   punto è (pagina x di y, annunci trovati). Alla fine **Vedi gli annunci**.

- **Ricerca non salvata** (temporanea): gira una volta, i suoi annunci si vedono solo aprendo
  quella ricerca, non crea notifiche e non rientra nella raccolta delle 3 ore. Resta in
  "Ricerche recenti" e dopo **7 giorni** dall'ultimo uso si cancella con i suoi annunci.
  Puoi salvarla in ogni momento ("Salva questa ricerca").
- **Ricerca salvata**: va in "Le mie ricerche", si aggiorna ogni 3 ore e crea notifiche
  (alla sua prima raccolta no, servirebbero solo a riempire la lista).
  "Non salvare più" la fa tornare temporanea; "Elimina" la toglie subito con i suoi annunci.
- Una raccolta alla volta: se ne lanci un'altra mentre una gira, aspetta in coda.
- Le ricerche create dal sito stanno in `data\searches.json`; quelle di `config.json`
  restano e si gestiscono dal sito come le altre.

## Fonti

| Fonte | Paese (valuta) | Come legge i dati |
|---|---|---|
| AutoScout24 | DE, AT, BE, ES, FR, IT, LU, NL | pagine dei risultati (usate e nuove) |
| Marktplaats | NL (+ venditori BE) | API JSON usata dal sito |
| 2dehands | BE (+ venditori NL) | API JSON usata dal sito |
| Otomoto | PL (PLN) | pagine dei risultati |
| Willhaben | AT | pagine dei risultati, ricerca per parola chiave |
| Blocket | SE (SEK) | pagine dei risultati |
| Finn.no | NO (NOK) | pagine dei risultati |

Le richieste sono lente apposta (3 secondi tra una pagina e l'altra).

**Non disponibili** (bloccano le richieste automatiche e non vanno aggirati; elenco anche in
`config.json`, voce `disabled_sources`): mobile.de, Leboncoin, AutoScout24.ch, Subito,
AutoTrader UK, Bilbasen, inventario Tesla. Coches.net non mette gli annunci nella pagina
(li carica dopo da un'API protetta).

**Doppioni**: la stessa auto è spesso su più siti. Se due annunci di siti diversi hanno stessa
ricerca, Paese e anno, km entro ±1% e prezzo entro ±2%, il sito mostra una sola scheda con
"anche su …" e i link agli altri annunci.

## Come aggiungere un'auto

In `config.json`, dentro `"searches"`, copia una ricerca e cambia i valori:

```json
{
  "name": "Porsche 911 GT3 2022+",
  "make": "porsche",
  "model": "911",
  "year_min": 2022,
  "year_max": 2026,
  "must_contain": ["gt3"],
  "exclude_words": ["noleggio", "LOA", "LLD", "lungo termine", "rental", "Miete"],
  "price_min_eur": 20000,
  "sources": ["autoscout24", "marktplaats", "2dehands", "otomoto", "willhaben", "blocket", "finn"]
}
```

- `make` e `model` sono quelli dell'indirizzo di AutoScout24 (es. `autoscout24.it/lst/porsche/911`),
  in minuscolo con il trattino al posto degli spazi (`model-s`).
- Gli altri siti cercano il testo "marca modello" e tengono solo gli annunci con marca e modello
  giusti. Se un sito usa un nome diverso, si può indicare solo per quel sito:
  `"source_ids": {"otomoto": {"model": "911"}}` (per Otomoto `make`/`model` sono le parti
  dell'indirizzo `otomoto.pl/osobowe/<make>/<model>`). Per cercare un testo diverso su tutti i
  siti a ricerca libera: `"query": "porsche 911 gt3"`.
- `must_contain`: parole che devono esserci (es. `plaid`). `exclude_words`: parole intere che
  scartano l'annuncio. `price_min_eur`: sotto questa cifra l'annuncio viene scartato (rate di
  leasing scambiate per prezzi).

Ogni fonte ha le sue impostazioni (pagine massime, pausa) nella voce con il suo nome; con
`"enabled": false` una fonte si spegne per tutte le ricerche.

## Sito

Una sola pagina (`site\index.html`) con i dati incorporati, che si apre senza server:

- **Annunci**: elenco con filtri (testo, modello, Paese, sito, nuove/usate, prezzo, km, anno) e
  ordinamento; ogni scheda ha galleria foto, tutti i dati, storico del prezzo, il sito di
  provenienza e il link all'annuncio originale.
- **Notifiche**: nuovi annunci, prezzi scesi o saliti e annunci tolti negli ultimi 90 giorni,
  raggruppati per giorno. Il numerino giallo indica quante non hai letto; "Segna tutte come
  lette" lo azzera. Alla prima raccolta in assoluto gli annunci non diventano notifiche.

## Raccolta automatica

`installa.bat` crea l'attività di Windows "ImportHelper": lancia `pythonw -m importhelper.background`
(nessuna finestra) ogni 3 ore e all'accesso. Per ricrearla: doppio clic su `pianifica.bat`.
Per toglierla: `disinstalla.bat`, oppure in PowerShell
`Unregister-ScheduledTask -TaskName ImportHelper -Confirm:$false`.
Il PC deve essere acceso (basta che l'utente sia connesso).

## Comandi

```
python -m importhelper           raccoglie gli annunci e aggiorna il sito
python -m importhelper list      mostra gli annunci attivi salvati
python -m importhelper export    crea data\annunci.csv (si apre con Excel)
python -m importhelper site      rigenera site\index.html (versione statica, senza "Cerca un'auto")
python -m importhelper.server    server del sito su http://localhost:8765 (lo accende già l'icona)
```

## Installazione a mano (per chi usa già Python)

Python 3.10 o più recente, poi nella cartella:

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
pianifica.bat
```

## Test

```
.venv\Scripts\python -m unittest discover tests
```

I test delle fonti usano pagine reali salvate (ridotte) in `tests\fixtures`.
