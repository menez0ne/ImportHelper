# ImportHelper

Aggregatore di annunci auto da tutta Europa. Cerca il modello che ti interessa sui principali
portali, converte i prezzi in euro con i cambi BCE e ti avvisa di nuovi annunci e variazioni di
prezzo. Gira in locale su Windows: nessun account, nessun dato inviato a terzi.

## Funzionalità

- **Ricerca multi-portale**: AutoScout24 (DE, AT, BE, ES, FR, IT, LU, NL), Marktplaats, 2dehands,
  Otomoto, Willhaben, Blocket, Finn.no.
- **Prezzi in euro** con i cambi ufficiali della BCE.
- **Scheda per ogni annuncio**: foto, chilometri, anno, Paese, storico del prezzo, link all'originale.
- **Doppioni uniti**: la stessa auto pubblicata su più siti compare una volta sola.
- **Notifiche** di nuovi annunci, ribassi, rialzi e annunci rimossi.
- **Aggiornamento automatico** delle ricerche salvate ogni 3 ore, in background.

## Installazione

Requisiti: Windows 10 o 11 e una connessione a Internet.

1. Scarica il progetto: **Code → Download ZIP**.
2. Estrai lo ZIP in una cartella definitiva, ad esempio `Documenti\ImportHelper`.
3. Fai doppio clic su **`installa.bat`**.
   Se Windows mostra "Windows ha protetto il PC", scegli **Ulteriori informazioni → Esegui comunque**.

L'installer installa Python se manca, prepara l'ambiente, attiva l'aggiornamento automatico e
crea l'icona **ImportHelper** sul Desktop. Si può rilanciare in qualsiasi momento per riparare
l'installazione (anche dopo aver spostato la cartella).

## Utilizzo

1. Apri **ImportHelper** dal Desktop: il sito si apre nel browser (http://localhost:8765).
2. In **Cerca un'auto** indica marca, modello e, se vuoi, anni, parole chiave e prezzo minimo.
3. **Salva** la ricerca per aggiornarla ogni 3 ore e ricevere le notifiche; le ricerche non
   salvate vengono eliminate dopo 7 giorni.

Il PC deve essere acceso perché l'aggiornamento automatico possa girare.

## File utili

| File | A cosa serve |
|---|---|
| `installa.bat` | Installa o ripara ImportHelper |
| `disinstalla.bat` | Rimuove aggiornamento automatico e icone (poi si può cancellare la cartella) |
| `avvia.bat` | Esegue subito una raccolta, mostrando l'avanzamento |
| `avvio-automatico-server.bat` | Avvia il sito a ogni accesso a Windows, utile per tenerlo nei segnalibri |
| `config.json` | Impostazioni avanzate delle fonti (pagine, pause tra le richieste) |

Annunci, ricerche e log sono salvati nella cartella `data`.

## Note

- Le richieste sono volutamente lente (3 secondi tra una pagina e l'altra) per rispettare i portali.
- Alcuni portali bloccano le richieste automatiche e non sono supportati: mobile.de, Leboncoin,
  AutoScout24.ch, Subito, AutoTrader UK, Bilbasen, Coches.net, inventario Tesla.

## Sviluppo

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m importhelper            # raccolta da riga di comando
.venv\Scripts\python -m importhelper.server     # sito su http://localhost:8765
.venv\Scripts\python -m unittest discover tests
```
