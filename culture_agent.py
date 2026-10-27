"""Agente quotidiano di cultura generale.

Ogni mattina genera con Gemini (ancorato alla ricerca Google) sei approfondimenti
fissi più uno a rotazione secondo il giorno della settimana, li manda su Telegram
con bottoni 👍/👎, aggiunge ogni giorno un quiz a intervalli e archivia tutto in Markdown.
"""

import html
import json
import os
import random
import re
import sys
import time
import unicodedata
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# ----------------------------------------------------------------------------
# Impostazioni
# ----------------------------------------------------------------------------

# Modelli provati in ordine: se uno risponde 404 (ritirato) si passa al successivo.
MODELS = (
    [os.environ["GEMINI_MODEL"]]
    if os.getenv("GEMINI_MODEL")
    else ["gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash"]
)
GROUNDING = os.getenv("GROUNDING", "1") != "0"  # ricerca Google per verificare i fatti
HISTORY_FILE = Path("history.json")
ARCHIVE_DIR = Path("archivio")
KEEP_SEEN = 60  # argomenti ricordati per categoria (per non ripetersi)
LOG_MAX = 1500  # voci massime nello storico
SEND_HOUR = 7  # ora locale (Milano) da cui l'invio è ammesso
SEND_UNTIL = 11  # ...fino a quest'ora esclusa (tollera i ritardi di GitHub)
TZ = ZoneInfo("Europe/Rome")
PAUSE = 6  # secondi tra una chiamata e l'altra (limiti del piano free)
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
UA = "DailyCultureBot/1.0 (progetto personale; https://github.com/CerroneDonato/DailyCulture)"

GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MESI = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
    "agosto", "settembre", "ottobre", "novembre", "dicembre",
]

GIORNI_ABBR = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
MESI_ABBR = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]
NOME = os.getenv("NOME", "Donato")  # per il saluto; NOME="" per toglierlo
DIVIDER = "─" * 22
LINK_EMOJI = {"wiki": "🔎", "commons": "🖼", "youtube": "▶️", "wiktionary": "📖", "source": "📄"}
KEYCAPS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]

THEMES = [
    "il tempo", "la misura", "il confine", "l'errore", "la simmetria", "l'infinito",
    "il caso", "il rumore e il segnale", "la memoria", "il viaggio", "la scrittura",
    "la mappa e il territorio", "il linguaggio", "l'equilibrio", "il potere",
    "il silenzio", "la copia e l'originale", "la scala (il piccolo e il grande)",
    "il fallimento", "la luce", "l'acqua", "il ritmo", "l'invisibile", "il numero",
    "la città", "il paradosso", "l'ordine e il caos", "la rete", "il gioco",
    "la fine", "l'inizio", "il metodo", "la bellezza", "la cura", "il clima",
    "l'imitazione", "la soglia", "il debito", "il vuoto", "la prova",
]
EPOCHS = [
    "l'Antichità classica", "il Medioevo", "il Rinascimento", "il Seicento",
    "il Settecento", "l'Ottocento", "il primo Novecento", "il secondo Novecento",
    "il XXI secolo",
]
AREAS = [
    "Italia", "Europa occidentale", "Europa orientale", "Russia", "Stati Uniti",
    "America Latina", "Africa", "Medio Oriente", "India", "Cina", "Giappone",
    "Oceania",
]
SCIENCE_BY_WEEKDAY = [  # lun ... dom: ambito della scheda "Scienze"
    "fisica", "biologia ed evoluzione", "chimica e scienza dei materiali",
    "astronomia e cosmologia", "geologia e scienze della Terra",
    "neuroscienze e medicina", "storia della scienza e teoria dell'informazione",
]
RESEARCH_AREAS = [
    "fisica e astronomia", "biologia e medicina", "chimica e materiali",
    "informatica e intelligenza artificiale", "ingegneria ed energia",
    "scienze della Terra e clima", "neuroscienze", "matematica",
]
WORD_KINDS = [
    "latinismi e grecismi", "arabismi", "termini di mestieri e artigianato",
    "arcaismi letterari", "parole di origine germanica", "termini marinareschi",
    "parole scientifiche passate nell'uso comune", "voci dialettali entrate in italiano",
    "parole dal francese o dallo spagnolo", "termini della filosofia e della retorica",
    "parole di altre lingue senza un equivalente italiano (con etimologia)",
]

NICHE = (
    "Livello: il lettore è un ingegnere con ottima cultura generale. Evita il canone "
    "scolastico e ciò che sa chiunque abbia fatto il liceo: scegli un argomento di "
    "nicchia, anche poco noto, ma sul quale sei certo dei fatti."
)
POPULAR = (
    "Livello: scegli un'opera o un autore riconoscibili ma non gli esempi più abusati; "
    "l'approfondimento però resta alto, con dettagli tecnici e di contesto."
)
DEFAULT_LENGTH = "4-5 paragrafi, circa 250-350 parole in totale (massimo 3500 caratteri)"
IMAGE_NOTE = (
    ' Nel campo "image_query" scrivi la migliore query per trovare su Wikimedia Commons '
    "una riproduzione o una foto di ciò che hai descritto (titolo e autore dell'opera, "
    "nome del luogo o dell'edificio, nome scientifico dell'organismo o nome del reperto), "
    "nella lingua originale."
)


def era_area(today=None):
    return f"epoca: {random.choice(EPOCHS)}; area geografica: {random.choice(AREAS)}"


# Categorie fisse (weekday assente) e categorie a rotazione (weekday 0=lunedì ... 6=domenica).
CATEGORIES = [
    {
        "key": "letteratura", "id": "let", "emoji": "📚", "label": "Letteratura", "image": True,
        "level": NICHE, "hint": era_area, "link": "wiki", "link_label": "Approfondisci",
        "brief": (
            "Proponi UN'opera letteraria (romanzo, racconto, saggio, raccolta di poesie, "
            "poema) oppure un autore trascurato. Nei paragrafi: 1) autore e contesto in cui "
            "nasce l'opera; 2) di cosa parla e qual è l'idea o la tesi centrale; 3) perché è "
            "notevole (stile, innovazione, influenza); 4) a chi parla e da dove cominciare. "
            "Se citi versi, al massimo 4 e solo di autori morti da oltre 70 anni." + IMAGE_NOTE
        ),
    },
    {
        "key": "storia", "id": "sto", "emoji": "🏛", "label": "Storia", "image": True,
        "level": NICHE, "hint": era_area, "link": "wiki", "link_label": "Approfondisci",
        "brief": (
            "Proponi UN episodio, processo o figura storica poco noti al grande pubblico "
            "(non le grandi date da manuale). Nei paragrafi: 1) contesto; 2) cosa è successo, "
            "con date e luoghi precisi; 3) cause e conseguenze; 4) perché è istruttivo o come "
            "cambia il modo di leggere il periodo." + IMAGE_NOTE
        ),
    },
    {
        "key": "arte", "id": "art", "emoji": "🎨", "label": "Arte", "image": True,
        "level": POPULAR, "hint": era_area, "link": "commons", "link_label": "Vedi l'opera",
        "brief": (
            "Proponi UN'opera d'arte visiva (pittura, scultura, fotografia, incisione). "
            "Nei paragrafi: 1) autore e contesto; 2) descrizione dell'opera (soggetto, "
            "composizione, tecnica, dove si trova); 3) come leggerla (simboli, innovazioni); "
            "4) perché conta e a quali altre opere si collega." + IMAGE_NOTE
        ),
    },
    {
        "key": "musica", "id": "mus", "emoji": "🎵", "label": "Musica", "image": True,
        "level": POPULAR, "hint": era_area, "link": "youtube", "link_label": "Ascolta",
        "brief": (
            "Proponi UN brano o un'opera musicale (qualsiasi genere: classica, jazz, rock, "
            "elettronica, folk...). Nei paragrafi: 1) autore o ensemble e contesto; 2) com'è "
            "fatto il brano (forma, armonia, ritmo, timbro) con dettagli tecnici; 3) cosa "
            "ascoltare con attenzione e in quale punto; 4) influenza e una curiosità sulla "
            "registrazione o versione consigliata." + IMAGE_NOTE
        ),
    },
    {
        "key": "scienze", "id": "sci", "emoji": "🔬", "label": "Scienze", "image": True,
        "level": NICHE, "hint": lambda today: f"ambito: {SCIENCE_BY_WEEKDAY[today.weekday()]}",
        "link": "wiki", "link_label": "Approfondisci",
        "brief": (
            "Proponi UN concetto, scoperta, esperimento o controversia scientifica. Il lettore "
            "ha formazione tecnica: puoi usare formule e ordini di grandezza, ma spiega "
            "l'intuizione, non solo il formalismo. Nei paragrafi: 1) il problema; 2) l'idea "
            "chiave; 3) come funziona o come fu scoperta; 4) implicazioni, limiti o questioni "
            "ancora aperte." + IMAGE_NOTE
        ),
    },
    {
        "key": "parole", "id": "par", "emoji": "🔤", "label": "Parole",
        "level": NICHE, "hint": lambda today: f"tipologia: {random.choice(WORD_KINDS)}",
        "link": "wiktionary", "link_label": "Wikizionario",
        "brief": (
            "Proponi TRE parole poco comuni, non inventate (di norma italiane; se la tipologia "
            "suggerita lo prevede, di altre lingue). Un paragrafo per parola: nel campo \"h\" la parola, nel campo \"t\" "
            "significato preciso, etimologia (lingua d'origine e forma originale "
            "solo se certe), sfumature d'uso, una frase d'esempio originale. Un eventuale "
            "quarto paragrafo può collegare le tre parole, solo se c'è un legame reale. Il "
            "campo \"title\" contiene le tre parole separate da virgole; il campo \"search\" "
            "contiene la prima parola, una sola."
        ),
    },
    # --- a rotazione ---
    {
        "key": "filosofia", "id": "fil", "emoji": "💭", "label": "Filosofia",
        "level": NICHE, "hint": era_area, "link": "wiki", "link_label": "Approfondisci",
        "brief": (
            "Proponi UN'idea, un argomento o un filosofo (anche non occidentale o poco "
            "frequentato). Nei paragrafi: 1) il problema da cui nasce; 2) la tesi centrale e "
            "la struttura dell'argomento; 3) le obiezioni principali e le repliche; 4) perché "
            "interessa oggi e da dove cominciare a leggere."
        ),
    },
    {
        "key": "cinema", "id": "cin", "emoji": "🎬", "label": "Cinema", "image": True,
        "level": POPULAR, "hint": era_area, "link": "wiki", "link_label": "Approfondisci",
        "brief": (
            "Proponi UN film (anche non anglofono, muto, documentario o d'animazione). Nei "
            "paragrafi: 1) regista e contesto di produzione; 2) la trama in breve, senza "
            "rivelare il finale; 3) le scelte formali (inquadrature, montaggio, suono) che lo "
            "rendono notevole; 4) l'influenza e dove inserirlo in un percorso di visione."
            + IMAGE_NOTE
        ),
    },
    {
        "key": "architettura", "id": "arc", "emoji": "🏗", "label": "Architettura",
        "image": True,
        "level": POPULAR, "hint": era_area, "link": "commons", "link_label": "Vedi le immagini",
        "brief": (
            "Proponi UN edificio, un'opera di ingegneria civile o un'idea urbanistica. Nei "
            "paragrafi: 1) autore, committente e contesto; 2) descrizione e soluzioni "
            "strutturali o formali; 3) i problemi tecnici affrontati e come furono risolti; "
            "4) l'eredità e dove vederlo." + IMAGE_NOTE
        ),
    },
    {
        "key": "ingegneria", "id": "ing", "emoji": "⚙️", "label": "Ingegneria",
        "level": NICHE, "hint": era_area, "link": "wiki", "link_label": "Approfondisci",
        "brief": (
            "Racconta UNA storia di tecnologia: un'invenzione, un progetto, un guasto o un "
            "disastro celebre, oppure una soluzione ingegneristica ingegnosa. Nei paragrafi: "
            "1) il problema; 2) la soluzione tecnica, con dettagli e numeri; 3) cosa è andato "
            "storto oppure cosa è stato innovativo; 4) la lezione di progettazione che se ne "
            "ricava."
        ),
    },
    {
        "key": "economia", "id": "eco", "emoji": "📈", "label": "Economia e società", "short": "Economia",
        "level": NICHE, "hint": era_area, "link": "wiki", "link_label": "Approfondisci",
        "brief": (
            "Proponi UN concetto, episodio o pensatore di economia e scienze sociali (storia "
            "economica, teoria dei giochi, istituzioni, demografia). Nei paragrafi: 1) la "
            "domanda di partenza; 2) il modello o l'evidenza; 3) casi concreti e limiti; "
            "4) le implicazioni."
        ),
    },
    {
        "key": "geografia", "id": "geo", "emoji": "🌍", "label": "Geografia",
        "image": True,
        "level": NICHE, "hint": lambda today: f"area: {random.choice(AREAS)}",
        "link": "wiki", "link_label": "Approfondisci",
        "brief": (
            "Proponi UN luogo, un fenomeno geografico o geologico, oppure una peculiarità "
            "culturale di un territorio poco noto. Nei paragrafi: 1) dove si trova e cos'è; "
            "2) come si è formato o la sua storia; 3) le caratteristiche sorprendenti, con "
            "dati; 4) perché è significativo." + IMAGE_NOTE
        ),
    },
    {
        "key": "saggio", "id": "sag", "emoji": "✍️", "label": "Il saggio della domenica", "short": "Saggio",
        "length": "6-7 paragrafi, circa 450-550 parole (massimo 3300 caratteri)",
        "level": NICHE,
        "hint": lambda today: (
            "ambito: scienza o tecnologia" if today.isocalendar()[1] % 2 == 0
            else "ambito a scelta tra " + ", ".join(
                random.sample(["storia", "letteratura", "filosofia", "arte", "lingua"], 3))
        ),
        "link": "wiki", "link_label": "Approfondisci",
        "brief": (
            "Scrivi un breve saggio su un tema libero e stimolante, con una tesi chiara, "
            "esempi concreti e una conclusione che apra una domanda. Tono da saggista."
        ),
    },
    {
        "key": "matematica", "id": "mat", "emoji": "🧮", "label": "Matematica",
        "level": NICHE,
        "hint": lambda today: "tipo: " + random.choice([
            "un teorema", "una dimostrazione elegante", "un paradosso", "un problema aperto",
            "un oggetto matematico poco noto", "un'applicazione inattesa"]),
        "link": "wiki", "link_label": "Approfondisci",
        "brief": (
            "Proponi UN argomento di matematica. Il lettore ha una formazione matematica "
            "avanzata (ingegneria matematica): puoi usare notazione e formule in Unicode e "
            "dare l'idea della dimostrazione, ma scegli temi fuori dai corsi standard. Nei "
            "paragrafi: 1) l'enunciato; 2) il contesto storico o il perché interessa; 3) "
            "l'idea della dimostrazione o della soluzione; 4) legami con altri campi e "
            "applicazioni. Nei campi \"challenge\" e \"solution\" metti un breve esercizio "
            "collegato all'argomento (risolvibile in pochi minuti) e la soluzione sintetica."
        ),
    },
    {
        "key": "ricerca", "id": "ric", "emoji": "🔭", "label": "Dalla ricerca", "short": "Ricerca",
        "needs_search": True,
        "level": NICHE, "hint": lambda today: f"ambito: {random.choice(RESEARCH_AREAS)}",
        "link": "source", "link_label": "Leggi la fonte",
        "brief": (
            "Racconta UN risultato scientifico o tecnologico recente (ultimi 12 mesi) già "
            "ben documentato: pubblicazione su rivista, annuncio di un'agenzia o di un "
            "laboratorio. USA la ricerca web per verificarlo; se non trovi conferme "
            "affidabili, scegli un altro risultato. Nei paragrafi: 1) cosa è stato fatto o "
            "scoperto, da chi e dove è stato pubblicato (rivista o istituzione, anno); 2) il "
            "metodo; 3) il risultato, con numeri; 4) limiti e cautele: cosa è confermato, "
            "cosa è preliminare, cosa resta da verificare."
        ),
    },
    {
        "key": "natura", "id": "nat", "emoji": "🌿", "label": "Natura", "image": True,
        "level": NICHE,
        "hint": lambda today: "ambito: " + random.choice([
            "zoologia", "botanica", "ecologia", "etologia", "microbiologia", "funghi e licheni",
            "paleontologia", "biologia marina"]),
        "link": "wiki", "link_label": "Approfondisci",
        "brief": (
            "Proponi UN organismo, fenomeno naturale o scoperta di storia naturale (animali, "
            "piante, funghi, microrganismi, ecosistemi). Nei paragrafi: 1) di cosa si tratta e "
            "dove vive o avviene; 2) il meccanismo biologico o fisico che lo rende possibile, "
            "con dati; 3) cosa ha rivelato alla scienza o come fu scoperto; 4) curiosità e, se "
            "pertinente, stato di conservazione." + IMAGE_NOTE
        ),
    },
    {
        "key": "archeologia", "id": "ant", "emoji": "🏺", "label": "Archeologia",
        "image": True, "level": NICHE, "hint": era_area,
        "link": "wiki", "link_label": "Approfondisci",
        "brief": (
            "Proponi UN sito, reperto o scoperta di archeologia o antropologia (anche recente "
            "o poco noto). Nei paragrafi: 1) dove, quando e come è stato scoperto; 2) cosa è "
            "stato trovato e con quali metodi è stato datato o analizzato; 3) cosa dice della "
            "società che lo ha prodotto; 4) interpretazioni discusse e questioni aperte."
            + IMAGE_NOTE
        ),
    },
    {
        "key": "cibo", "id": "cib", "emoji": "🍝", "label": "Cibo e cultura", "short": "Cibo",
        "level": NICHE, "hint": era_area, "link": "wiki", "link_label": "Approfondisci",
        "brief": (
            "Proponi UN piatto, ingrediente o tecnica di cucina, visto dalla storia, dalla "
            "scienza (chimica, fisica, microbiologia) o dall'antropologia. Nei paragrafi: 1) di "
            "cosa si tratta e la sua origine; 2) la scienza che c'è dietro (reazioni, "
            "trasformazioni, fermentazioni), con dettagli; 3) storia e diffusione; 4) varianti "
            "e curiosità."
        ),
    },
]

# Sempre presenti ogni giorno
FIXED = ["letteratura", "storia", "scienze"]
# Quattro slot a rotazione per giorno (0=lunedì ... 6=domenica): il primo è scientifico o
# tecnico, gli altri sono di cultura varia. Una tupla significa "a settimane alterne".
SCHEDULE = {
    0: ("ingegneria", "parole", "natura", "arte"),
    1: ("matematica", "arte", "geografia", "musica"),
    2: ("ricerca", "filosofia", "archeologia", ("architettura", "cinema")),
    3: ("ingegneria", "parole", "natura", "geografia"),
    4: ("matematica", "musica", "cibo", ("cinema", "architettura")),
    5: ("ricerca", ("geografia", "cinema", "architettura"), ("archeologia", "cibo"), "filosofia"),
    6: ("saggio", "economia", ("arte", "musica"), ("natura", "geografia")),
}
FALLBACK = ["natura", "archeologia", "cibo", "filosofia", "economia", "geografia"]


def todays_categories(today):
    by_key = {c["key"]: c for c in CATEGORIES}
    keys = list(FIXED)
    for slot in SCHEDULE[today.weekday()]:
        key = slot[today.isocalendar()[1] % len(slot)] if isinstance(slot, tuple) else slot
        if key in keys:  # mai due schede uguali nello stesso giorno
            key = next(k for k in FALLBACK if k not in keys)
        keys.append(key)
    return [by_key[k] for k in keys]


SYSTEM = """Sei un curatore di cultura generale per un lettore adulto, ingegnere, colto e curioso.
Scrivi in italiano, con tono sobrio e denso, senza retorica e senza elenchi puntati.

Precisione prima di tutto: non inventare date, nomi, titoli o citazioni. Se non sei
sicuro di un dettaglio, omettilo oppure scegli un altro argomento. Se hai accesso alla
ricerca web, usala per verificare i fatti. Non riportare citazioni testuali lunghe di
opere protette da diritti. Per le formule usa simboli Unicode e testo semplice (≤, ∑, √,
x², π, ∫...), mai LaTeX.

Formattazione: ogni paragrafo ha un titoletto breve (1-3 parole, per esempio "Contesto",
"L'idea", "Perché conta") coerente con la struttura richiesta. Nel testo evidenzia 3-6
termini chiave (nomi, date, concetti) racchiudendoli tra doppi asterischi, per esempio
**Landauer**; non usare altri simboli di formattazione. Il campo "facts" contiene da 2 a 4
dati essenziali di scheda tecnica (autore, anno, luogo, durata, tecnica, ambito...); per
le parole lascia la lista vuota.

Rispondi SOLO con un oggetto JSON valido, senza testo prima o dopo e senza blocchi di
codice, con questo schema:
{
  "title": "argomento in poche parole",
  "subtitle": "una riga che incuriosisce",
  "facts": [{"k": "Autore", "v": "..."}],
  "paragraphs": [{"h": "titoletto", "t": "testo del paragrafo"}],
  "recap": "2-3 frasi con i fatti chiave da ricordare (nomi, date, numeri), comprensibili da sole",
  "key": "identificativo breve dell'argomento per lo storico (es. 'Autore - Titolo')",
  "search": "query di ricerca per approfondire",
  "image_query": "solo se richiesto, altrimenti stringa vuota",
  "challenge": "solo se richiesto: breve esercizio, altrimenti stringa vuota",
  "solution": "solo se richiesto: soluzione sintetica, altrimenti stringa vuota"
}"""

REVIEW_SYSTEM = """Sei un tutor che prepara domande per un quiz per un lettore adulto, ingegnere.
Ricevi alcune schede (categoria, titolo, riassunto dei fatti chiave). Per OGNI scheda
scrivi UNA domanda, basandoti SOLO sul riassunto della scheda. La domanda deve essere
comprensibile da sola (non scrivere "nel testo" o "nella scheda"), richiedere un fatto o
un ragionamento preciso e avere una risposta breve (massimo 2 frasi).

Per ogni domanda aggiungi anche la versione a scelta multipla: "options" con 4 opzioni
brevi (massimo 80 caratteri ciascuna), una sola corretta e tre distrattori plausibili ma
sbagliati; "correct" è l'indice (0-3) dell'opzione corretta; "explanation" è una frase di
spiegazione (massimo 150 caratteri).

Rispondi SOLO con JSON valido, senza altro testo, con questo schema:
{"questions": [{"q": "domanda", "a": "risposta", "options": ["A", "B", "C", "D"],
"correct": 0, "explanation": "spiegazione", "topic": "titolo della scheda"}]}"""

CONTENT_FIELDS = ("title", "subtitle", "paragraphs", "key")


# ----------------------------------------------------------------------------
# Utilità
# ----------------------------------------------------------------------------

def data_it(d, year=True, short=False):
    if short:
        return f"{GIORNI_ABBR[d.weekday()]} {d.day} {MESI_ABBR[d.month - 1]}"
    s = f"{GIORNI[d.weekday()]} {d.day} {MESI[d.month - 1]}"
    return f"{s} {d.year}" if year else s


def week_theme(d):
    return THEMES[d.isocalendar()[1] % len(THEMES)]


def chat_id():
    return os.environ["TELEGRAM_CHAT_ID"]


def esc(text):
    """Escape per il testo HTML di Telegram (gli apostrofi restano com'è)."""
    return html.escape(str(text), quote=False)


def esc_attr(text):
    """Escape per gli attributi (href)."""
    return html.escape(str(text), quote=True).replace("&#x27;", "'")


# ----------------------------------------------------------------------------
# Stato (history.json)
# ----------------------------------------------------------------------------

def load_state():
    """Legge lo stato, convertendo i formati precedenti."""
    state = {"_last_sent": "", "_offset": 0, "log": [], "ratings": {}}
    if not HISTORY_FILE.exists():
        return state
    raw = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))

    def old(key, cat=""):
        return {"id": "", "date": "", "cat": cat, "key": str(key), "title": str(key), "recap": ""}

    if isinstance(raw, list):  # primo formato: lista di stringhe
        state["log"] = [old(k) for k in raw]
    elif "log" in raw:  # formato attuale
        state.update(raw)
    else:  # secondo formato: {categoria: [chiavi]}
        state["_last_sent"] = raw.get("_last_sent", "")
        for cat, vals in raw.items():
            if cat.startswith("_") or not isinstance(vals, list):
                continue
            state["log"] += [old(k, "" if cat == "vecchio" else cat) for k in vals]
    return state


def save_state(state):
    state["log"] = state["log"][-LOG_MAX:]
    ids = {x.get("id") for x in state["log"]}
    state["ratings"] = {k: v for k, v in state["ratings"].items() if k in ids}
    HISTORY_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def should_send(state):
    """GitHub usa l'ora UTC e può ritardare: si invia una volta al giorno tra le 7 e le 11."""
    if os.getenv("FORCE"):
        return True
    now = datetime.now(TZ)
    if not (SEND_HOUR <= now.hour < SEND_UNTIL):
        return False
    return state.get("_last_sent") != now.date().isoformat()


# ----------------------------------------------------------------------------
# Gemini
# ----------------------------------------------------------------------------

def extract_json(text):
    text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("nessun JSON nella risposta")
    return json.loads(text[start:end + 1])


def extract_sources(cand):
    chunks = (cand.get("groundingMetadata") or {}).get("groundingChunks") or []
    out, seen = [], set()
    for ch in chunks:
        web = ch.get("web") or {}
        uri, title = web.get("uri"), web.get("title")
        if uri and title and title not in seen:
            seen.add(title)
            out.append((title, uri))
    return out[:3]


def norm_paragraphs(raw):
    """Porta i paragrafi al formato [{"h": titoletto, "t": testo}] (accetta anche stringhe)."""
    if isinstance(raw, (str, dict)):
        raw = [raw]
    out = []
    for p in raw or []:
        if isinstance(p, dict):
            t = str(p.get("t") or p.get("text") or "").strip()
            h = str(p.get("h") or p.get("heading") or "").strip()
        else:
            t, h = str(p).strip(), ""
        if t:
            out.append({"h": h[:40], "t": t})
    return out


def norm_facts(raw):
    out = []
    for f in raw or []:
        if isinstance(f, dict):
            k, v = f.get("k"), f.get("v")
        elif isinstance(f, (list, tuple)) and len(f) == 2:
            k, v = f
        else:
            continue
        if k and v:
            out.append((str(k).strip()[:30], str(v).strip()[:80]))
    return out[:4]


def call_model(model, prompt, system, grounded, required):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    gen = {"temperature": 1.0}
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": gen,
    }
    if grounded:
        body["tools"] = [{"google_search": {}}]  # con la ricerca il JSON si chiede nel prompt
    else:
        gen["responseMimeType"] = "application/json"
    headers = {"x-goog-api-key": os.environ["GEMINI_API_KEY"]}
    for attempt in range(4):
        r = requests.post(url, headers=headers, json=body, timeout=120)
        if r.status_code in (429, 500, 503):
            time.sleep(15 * (attempt + 1))
            continue
        if r.status_code == 404:
            raise LookupError(model)
        r.raise_for_status()
        try:
            cand = r.json()["candidates"][0]
            parts = cand["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            data = extract_json(text)
            for field in required:
                if not data.get(field):
                    raise KeyError(field)
            if "paragraphs" in data:
                data["paragraphs"] = norm_paragraphs(data["paragraphs"])
                if not data["paragraphs"]:
                    raise KeyError("paragraphs")
                data["facts"] = norm_facts(data.get("facts"))
            data["_sources"] = extract_sources(cand) if grounded else []
            return data
        except (KeyError, IndexError, ValueError, TypeError, AttributeError) as exc:
                print(
                    f"RISPOSTA GEMINI NON VALIDA: {type(exc).__name__}: {exc}; "
                    f"HTTP={r.status_code}; risposta={r.text[:1500]}",
                    file=sys.stderr,
                )
                time.sleep(5)  # risposta malformata: riprovo

    raise RuntimeError(f"Gemini ({model}) non ha dato una risposta valida")

def call_gemini(prompt, system=SYSTEM, grounded=GROUNDING, required=CONTENT_FIELDS,
                require_search=False):
    variants = [True] if require_search else ([True, False] if grounded else [False])
    for model in MODELS:
        for use_search in variants:
            try:
                data = call_model(model, prompt, system, use_search, required)
                print(f"Modello usato: {model} (ricerca web: {'sì' if use_search else 'no'})")
                return data
            except LookupError:
                print(f"Modello non trovato (404): {model}, provo il successivo")
                break
            except Exception as exc:  # senza ricerca, poi modello successivo
                print(f"{model} (ricerca web: {use_search}) non riuscito: {exc}", file=sys.stderr)
    raise RuntimeError(f"Nessun modello disponibile tra: {', '.join(MODELS)}")


def build_prompt(cat, state, today):
    log = state["log"]
    ratings = state["ratings"]
    seen = [x["key"] for x in log if x.get("cat") in (cat["key"], "")][-KEEP_SEEN:]
    liked = [x["title"] for x in log if x.get("cat") == cat["key"] and ratings.get(x.get("id")) == 1][-8:]
    disliked = [x["title"] for x in log if x.get("cat") == cat["key"] and ratings.get(x.get("id")) == -1][-8:]
    lines = [
        f"Oggi è {data_it(today)}. Prepara il messaggio di oggi per la categoria «{cat['label']}».",
        cat["brief"],
        cat["level"],
        f"Lunghezza: {cat.get('length', DEFAULT_LENGTH)}.",
    ]
    hint = cat["hint"](today) if cat.get("hint") else ""
    if hint:
        lines.append(f"Spunto di varietà (non vincolante se non trovi nulla di certo): {hint}")
    lines.append(
        f"Tema della settimana: «{week_theme(today)}». Collegalo solo se il legame è "
        "naturale e non forzato; altrimenti ignoralo."
    )
    if liked:
        lines.append("Argomenti che il lettore ha apprezzato (cerca affinità di taglio e "
                     "profondità, senza ripeterli): " + "; ".join(liked))
    if disliked:
        lines.append("Argomenti poco graditi (evita temi e taglio simili): " + "; ".join(disliked))
    lines.append("NON riproporre argomenti già dati: " + ("; ".join(seen) or "nessuno"))
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Telegram
# ----------------------------------------------------------------------------

def tg(method, payload=None, files=None):
    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/{method}"
    if files:
        r = requests.post(url, data=payload, files=files, timeout=60)
    else:
        r = requests.post(url, json=payload or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def send_text(text, markup=None):
    payload = {
        "chat_id": chat_id(),
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if markup:
        payload["reply_markup"] = markup
    return tg("sendMessage", payload)


def vote_buttons(entry_id):
    return {"inline_keyboard": [[
        {"text": "👍 Mi piace", "callback_data": f"up:{entry_id}"},
        {"text": "👎 Non per me", "callback_data": f"down:{entry_id}"},
    ]]}


def process_feedback(state):
    """Legge i voti dati dall'ultima esecuzione (Telegram li conserva per 24 ore)."""
    try:
        res = tg("getUpdates", {
            "offset": state["_offset"],
            "allowed_updates": ["callback_query"],
            "timeout": 0,
        })
    except Exception as exc:
        print(f"Impossibile leggere i voti: {exc}", file=sys.stderr)
        return
    for upd in res.get("result", []):
        state["_offset"] = max(state["_offset"], upd["update_id"] + 1)
        cq = upd.get("callback_query") or {}
        msg = cq.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != str(chat_id()):
            continue
        action, _, entry_id = (cq.get("data") or "").partition(":")
        if action not in ("up", "down") or not entry_id:
            continue
        state["ratings"][entry_id] = 1 if action == "up" else -1
        label = "👍 Voto registrato" if action == "up" else "👎 Voto registrato"
        old_rows = (msg.get("reply_markup") or {}).get("inline_keyboard") or []
        rows = [r for r in old_rows if r and all("url" in b for b in r)]  # tiene il link
        rows.append([{"text": label, "callback_data": "noop"}])
        try:
            tg("editMessageReplyMarkup", {
                "chat_id": msg["chat"]["id"],
                "message_id": msg["message_id"],
                "reply_markup": {"inline_keyboard": rows},
            })
        except Exception:
            pass  # il voto è comunque registrato


def fetch_commons_image(query):
    """Cerca su Wikimedia Commons un'immagine pertinente; None se non è affidabile."""
    headers = {"User-Agent": UA}
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 8,
        "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1280,
        "iiextmetadatafilter": "Artist|LicenseShortName",
    }
    r = requests.get("https://commons.wikimedia.org/w/api.php", params=params,
                     headers=headers, timeout=30)
    r.raise_for_status()
    pages = (r.json().get("query") or {}).get("pages") or {}
    tokens = set(re.findall(r"\w{4,}", query.lower()))
    if not tokens:
        return None
    needed = 2 if len(tokens) >= 2 else 1
    for page in sorted(pages.values(), key=lambda p: p.get("index", 99)):
        info = (page.get("imageinfo") or [{}])[0]
        title = page.get("title", "")
        if info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        if info.get("thumbwidth", info.get("width", 0)) < 600:
            continue
        hits = sum(1 for t in tokens if t in title.lower())
        if hits < needed:
            continue  # il nome del file non corrisponde: meglio nessuna immagine
        img = requests.get(info.get("thumburl") or info["url"], headers=headers, timeout=60)
        img.raise_for_status()
        if len(img.content) < 9_000_000:
            name = re.sub(r"^File:|\.[A-Za-z]{3,4}$", "", title)
            return img.content, name, title, image_meta(title, info)
    return None


def strip_tags(text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(str(text or "")))).strip()


def image_meta(file_title, info):
    """Riferimento stabile all'immagine per l'archivio: URL Special:FilePath e crediti brevi."""
    meta = info.get("extmetadata") or {}
    artist = strip_tags((meta.get("Artist") or {}).get("value"))[:60]
    license_ = strip_tags((meta.get("LicenseShortName") or {}).get("value"))[:30]
    file_name = re.sub(r"^File:", "", file_title).replace(" ", "_")
    return {
        "title": file_title,
        "url": "https://commons.wikimedia.org/wiki/Special:FilePath/"
               + urllib.parse.quote(file_name) + "?width=1280",
        "credit": " · ".join(x for x in [artist, license_, "Wikimedia Commons"] if x),
    }


def send_image(cat, query):
    """Foto dell'opera/luogo prima del testo; restituisce i dati dell'immagine trovata su Commons.

    Se l'invio a Telegram fallisce i dati restano validi per l'archivio. Nessuna immagine = None.
    """
    try:
        found = fetch_commons_image(query)
    except Exception as exc:
        print(f"Immagine non trovata: {exc}", file=sys.stderr)
        return None
    if not found:
        return None
    content, name, _, meta = found
    try:
        caption = f"{cat['emoji']} <b>{esc(name[:180])}</b>\n<i>Wikimedia Commons</i>"
        tg("sendPhoto", {"chat_id": chat_id(), "caption": caption, "parse_mode": "HTML"},
           files={"photo": ("immagine.jpg", content)})
    except Exception as exc:
        print(f"Immagine non inviata: {exc}", file=sys.stderr)
    return meta


# ----------------------------------------------------------------------------
# Formattazione dei messaggi
# ----------------------------------------------------------------------------

def fold(text):
    """Minuscole senza accenti, per confrontare titoli in lingue diverse."""
    return "".join(c for c in unicodedata.normalize("NFD", str(text).lower())
                   if unicodedata.category(c) != "Mn")


def tokens_of(text):
    return {t for t in re.findall(r"\w{4,}", fold(text))}


def enough(hits, n):
    """Almeno metà dei termini, e tutti se sono uno o due."""
    return n > 0 and hits >= max((n + 1) // 2, min(n, 2))


def relevant(query, title):
    """Il titolo trovato parla dello stesso argomento della query, in entrambe le direzioni:
    i termini della query compaiono nel titolo e il titolo non aggiunge soprattutto altro
    (evita che "dilemma" porti a una pagina su Evangelion)."""
    q, t = tokens_of(query), tokens_of(title)
    folded_title, folded_query = fold(title), fold(query)
    if not enough(sum(1 for w in q if w in folded_title), len(q)):
        return False
    return sum(1 for w in t if w in folded_query) >= (len(t) + 1) // 2


def wiki_article(queries):
    """URL di un articolo Wikipedia che esiste davvero ed è pertinente (prima it, poi en)."""
    for lang in ("it", "en"):
        for query in queries:
            try:
                r = requests.get(
                    f"https://{lang}.wikipedia.org/w/api.php",
                    params={"action": "query", "list": "search", "srsearch": query,
                            "srlimit": 5, "format": "json"},
                    headers={"User-Agent": UA}, timeout=20,
                )
                r.raise_for_status()
                for hit in (r.json().get("query") or {}).get("search", []):
                    if relevant(query, hit["title"]):
                        slug = urllib.parse.quote(hit["title"].replace(" ", "_"))
                        return lang, f"https://{lang}.wikipedia.org/wiki/{slug}"
            except Exception as exc:
                print(f"Ricerca Wikipedia ({lang}) non riuscita: {exc}", file=sys.stderr)
    return None


def wiktionary_page(word):
    """URL della voce su Wikizionario, solo se la pagina esiste (it, poi en)."""
    if not word:
        return None
    for lang in ("it", "en"):
        try:
            r = requests.get(
                f"https://{lang}.wiktionary.org/w/api.php",
                params={"action": "query", "titles": word, "format": "json"},
                headers={"User-Agent": UA}, timeout=20,
            )
            r.raise_for_status()
            for page in ((r.json().get("query") or {}).get("pages") or {}).values():
                if "missing" not in page and "invalid" not in page:
                    slug = urllib.parse.quote(page["title"].replace(" ", "_"))
                    return lang, f"https://{lang}.wiktionary.org/wiki/{slug}"
        except Exception as exc:
            print(f"Ricerca Wikizionario ({lang}) non riuscita: {exc}", file=sys.stderr)
    return None


def resolve_link(cat, data, image_title=None):
    """Restituisce (url, etichetta) di un link che funziona davvero, oppure (None, None)."""
    kind, label = cat["link"], cat["link_label"]
    query = str(data.get("search") or data["title"])
    if kind == "youtube":  # la pagina dei risultati esiste sempre
        return "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query), label
    if kind == "commons":
        if image_title:  # pagina del file trovato davvero
            return "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(image_title.replace(" ", "_")), label
        return "https://commons.wikimedia.org/w/index.php?search=" + urllib.parse.quote_plus(query), label
    if kind == "wiktionary":
        word = (query.split() or [""])[0].lower().strip(",.;:()'\"")
        found = wiktionary_page(word)
        if found:
            lang, url = found
            return url, label if lang == "it" else f"{label} (inglese)"
        return None, None
    if kind == "source":  # la prima fonte web verificata
        srcs = data.get("_sources") or []
        return (srcs[0][1], label) if srcs else (None, None)
    found = wiki_article([query, str(data["title"])])
    if found:
        lang, url = found
        return url, label if lang == "it" else f"{label} (inglese)"
    return None, None


def resolve_sources(sources):
    """Le fonti della ricerca Google sono link di rimbalzo che scadono: li trasformo negli
    indirizzi veri e scarto quelli non risolti o morti."""
    out = []
    for title, uri in sources:
        try:
            r = requests.get(uri, headers={"User-Agent": BROWSER_UA}, timeout=10,
                             allow_redirects=True, stream=True)
            final, status = r.url, r.status_code
            r.close()
        except Exception:
            continue
        host = urllib.parse.urlparse(final).netloc.lower()
        if status in (404, 410) or status >= 500 or "google" in host:
            continue
        out.append((title, final))
    return out


def hashtag(text):
    slug = re.sub(r"\W+", "_", str(text).lower()).strip("_")
    return f"#{slug}" if slug else ""


def reading_minutes(paragraphs):
    words = sum(len(p["t"].split()) for p in paragraphs)
    return max(1, round(words / 200))


def render_text(text):
    """Escape HTML e **termini chiave** in grassetto."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc(text))


def render_paragraph(cat, p):
    h, t = p["h"], p["t"]
    if cat["key"] == "parole":
        if not h:  # formato "parola — significato"
            head, sep, rest = t.partition(" — ")
            if sep and len(head) <= 40:
                h, t = head, rest
        if h:
            return f"🔸 <b>{esc(h)}</b> — {render_text(t)}"
    if h:
        return f"▸ <b>{esc(h)}</b>\n{render_text(t)}"
    return render_text(t)


def format_message(cat, d, today, link=None):
    e = esc
    label = cat.get("short", cat["label"]).upper()
    head = f"{cat['emoji']} <b>{e(label)}</b>  ·  <i>{data_it(today, short=True)}</i>\n{DIVIDER}"
    title = (
        f"<b>{e(d['title'])}</b>\n<i>{e(d['subtitle'])}</i>\n"
        f"⏱ {reading_minutes(d['paragraphs'])} min di lettura"
    )
    facts = ""
    if d.get("facts"):
        facts = "<blockquote>" + "\n".join(
            f"<b>{e(k)}</b> · {e(v)}" for k, v in d["facts"]) + "</blockquote>"
    paras = [render_paragraph(cat, p) for p in d["paragraphs"]]
    recap = (
        f"<blockquote>📌 <b>Da ricordare</b>\n{render_text(d['recap'])}</blockquote>"
        if d.get("recap") else ""
    )
    sources = ""
    if d.get("_sources"):
        sources = "📎 " + " · ".join(
            f'<a href="{esc_attr(u)}">{e(t)}</a>' for t, u in d["_sources"]
        )
    challenge = ""
    if d.get("challenge") and d.get("solution"):
        challenge = (
            f"🧩 <b>Prova tu</b>\n{e(d['challenge'])}\n<tg-spoiler>{e(d['solution'])}</tg-spoiler>"
        )
    tags = "  ".join(t for t in [hashtag(cat["key"]), hashtag(week_theme(today))] if t)

    def assemble():
        return "\n\n".join(
            x for x in [head, title, facts, *paras, challenge, recap, sources, tags] if x)

    while len(assemble()) > 4000 and len(paras) > 1:  # limite Telegram: 4096 caratteri
        paras.pop()
    if len(assemble()) > 4000:
        sources = ""
    return assemble()


def message_markup(entry_id, link, cat, label=None):
    """Bottone di approfondimento (se il link c'è) e riga di voto."""
    rows = []
    if link:
        emoji = LINK_EMOJI.get(cat["link"], "🔎")
        rows.append([{"text": f"{emoji} {label or cat['link_label']}", "url": link}])
    rows += vote_buttons(entry_id)["inline_keyboard"]
    return {"inline_keyboard": rows}


def send_card(cat, text, entry_id, link, label=None):
    try:
        return send_text(text, markup=message_markup(entry_id, link, cat, label))
    except requests.HTTPError:  # link non accettato da Telegram: resta la riga di voto
        return send_text(text, markup=message_markup(entry_id, None, cat))


def greeting(today, state, todays, weekly):
    dated = {x["date"] for x in state["log"] if x.get("date")}
    total = sum(1 for x in state["log"] if x.get("date"))
    chips = " · ".join(f"{c['emoji']} {c.get('short', c['label'])}" for c in todays)
    chips += " · 🧠 Quiz"
    name = f", {esc(NOME)}" if NOME else ""
    lines = [
        f"☀️ <b>Buongiorno{name}</b>",
        f"<i>{data_it(today)}</i>",
        DIVIDER,
        "",
        f"<blockquote>🧭 Tema della settimana\n<b>{esc(week_theme(today))}</b></blockquote>",
        "",
        "<b>Oggi</b>",
        chips,
    ]
    if total:
        lines += ["", f"<i>📆 Giorno {len(dated | {today.isoformat()})} · {total} approfondimenti finora</i>"]
    return "\n".join(lines)


def pick_review_items(state, today, weekly):
    by_date = {}
    for x in state["log"]:
        if x.get("date") and x.get("recap"):
            by_date.setdefault(x["date"], []).append(x)
    # Quiz quotidiano a intervalli (1, 2, 4, 7, 14 giorni fa); la domenica, tutta la settimana.
    plan = {**{d: 1 for d in range(1, 8)}, 14: 1} if weekly else {1: 2, 2: 1, 4: 1, 7: 1, 14: 1}
    items = []
    for delta, n in plan.items():
        pool = by_date.get((today - timedelta(days=delta)).isoformat(), [])
        items += random.sample(pool, min(n, len(pool)))
    return items


def generate_review(items):
    cards = "\n".join(
        f"- Categoria: {x['cat']}; titolo: {x['title']}; riassunto: {x['recap']}" for x in items
    )
    return call_gemini(
        f"Schede da cui trarre le domande ({len(items)}):\n{cards}",
        system=REVIEW_SYSTEM, grounded=False, required=("questions",),
    )


MAX_POLLS = 2  # domande del quiz proposte come sondaggi a risposta multipla


def clean_questions(d):
    out = []
    for q in d.get("questions", []):
        if isinstance(q, dict) and q.get("q") and q.get("a"):
            out.append({
                "q": str(q["q"]), "a": str(q["a"]), "topic": str(q.get("topic", "")),
                "options": q.get("options"), "correct": q.get("correct"),
                "explanation": str(q.get("explanation") or ""),
            })
    return out[:8]


def poll_valid(q):
    opts = q.get("options")
    if not isinstance(opts, list) or not 3 <= len(opts) <= 4:
        return False
    opts = [str(o).strip() for o in opts]
    try:
        correct = int(q.get("correct"))
    except (TypeError, ValueError):
        return False
    return (
        0 <= correct < len(opts)
        and all(o and len(o) <= 100 for o in opts)
        and len(set(opts)) == len(opts)
        and len(q["q"]) <= 280
    )


def make_poll(q):
    opts = [str(o).strip() for o in q["options"]]
    right = opts[int(q["correct"])]
    random.shuffle(opts)  # la risposta giusta non è sempre nello stesso posto
    return {
        "question": q["q"], "options": opts, "correct": opts.index(right), "answer": right,
        "explanation": (q.get("explanation") or q["a"])[:195],
    }


def send_poll(poll):
    tg("sendPoll", {
        "chat_id": chat_id(),
        "question": "🧠 " + poll["question"],
        "options": [{"text": o} for o in poll["options"]],
        "type": "quiz",
        "correct_option_id": poll["correct"],
        "explanation": poll["explanation"],
        "is_anonymous": False,
    })


def format_review(questions, today, weekly, n_polls=0):
    e = esc
    title = "QUIZ DELLA DOMENICA" if weekly else "QUIZ"
    intro = ("Domande su tutta la settimana." if weekly
             else "Domande su ciò che hai letto 1, 2, 4, 7 e 14 giorni fa.")
    lines = [
        f"🧠 <b>{title}</b>  ·  <i>{data_it(today, short=True)}</i>",
        DIVIDER,
        f"<i>{intro}" + (" Tocca il riquadro nascosto per vedere la risposta.</i>" if questions else "</i>"),
        "",
    ]
    for i, q in enumerate(questions[:len(KEYCAPS)]):
        lines.append(f"{KEYCAPS[i]} {e(q['q'])}")
        lines.append(f"      ↳ <tg-spoiler>{e(q['a'])}</tg-spoiler>")
        lines.append("")
    if n_polls:
        lines += [f"👇 {n_polls} a scelta multipla qui sotto", ""]
    lines.append(hashtag("quiz"))
    return "\n".join(lines)[:4000]


def send_quiz(questions, today, weekly):
    """Due domande come sondaggi a risposta multipla, le altre con la risposta nascosta."""
    ok = [i for i, q in enumerate(questions) if poll_valid(q)]
    random.shuffle(ok)
    chosen = sorted(ok[:MAX_POLLS])
    plain = [q for i, q in enumerate(questions) if i not in chosen]
    polls = [make_poll(questions[i]) for i in chosen]
    send_text(format_review(plain, today, weekly, len(polls)))
    for poll in polls:
        try:
            send_poll(poll)
        except Exception as exc:  # se Telegram rifiuta il sondaggio: domanda con spoiler
            print(f"Sondaggio non inviato: {exc}", file=sys.stderr)
            send_text(f"🧠 {esc(poll['question'])}\n      ↳ <tg-spoiler>{esc(poll['answer'])}</tg-spoiler>")


# ----------------------------------------------------------------------------
# Archivio Markdown
# ----------------------------------------------------------------------------

def entry_markdown(cat, d, link, label=None):
    lines = [f"## {cat['emoji']} {cat['label']}: {d['title']}", "", f"*{d['subtitle']}*", ""]
    image = d.get("_image")
    if image and image.get("url"):
        alt = re.sub(r"[\[\]\n]", " ", image.get("credit") or "Wikimedia Commons").strip()
        lines += [f"![{alt}]({image['url']})", ""]
    for k, v in d.get("facts", []):
        lines.append(f"- **{k}:** {v}")
    if d.get("facts"):
        lines.append("")
    for p in d["paragraphs"]:
        if p["h"]:
            lines += [f"### {p['h']}", ""]
        lines += [p["t"], ""]
    if d.get("challenge") and d.get("solution"):
        lines += [f"**🧩 Prova tu:** {d['challenge']}", "", f"> *Soluzione:* {d['solution']}", ""]
    if d.get("recap"):
        lines += [f"> 📌 {d['recap']}", ""]
    if link:
        lines.append(f"[{label or cat['link_label']}]({link})")
    for title, uri in d.get("_sources", []):
        lines.append(f"- Fonte: [{title}]({uri})")
    return "\n".join(lines)


def archive_day(today, sections, questions, weekly):
    folder = ARCHIVE_DIR / str(today.year)
    folder.mkdir(parents=True, exist_ok=True)
    out = [f"# {data_it(today)}", "", f"Tema della settimana: *{week_theme(today)}*", ""]
    for md in sections:
        out += [md, ""]
    if questions:
        out += ["## 🧠 " + ("Quiz della domenica" if weekly else "Quiz"), ""]
        for i, q in enumerate(questions, 1):
            out += [f"{i}. {q['q']}", f"   - *Risposta:* {q['a']}", ""]
    (folder / f"{today.isoformat()}.md").write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def archive_week(state, today):
    year, week, _ = today.isocalendar()
    labels = {c["key"]: f"{c['emoji']} {c['label']}" for c in CATEGORIES}
    by_day = {}
    for x in state["log"]:
        if not x.get("date"):
            continue
        d = date.fromisoformat(x["date"])
        if d.isocalendar()[:2] == (year, week):
            by_day.setdefault(d, []).append(x)
    out = [f"# Settimana {year}-W{week:02d}", "", f"Tema: *{week_theme(today)}*", ""]
    for d in sorted(by_day):
        out += [f"## {data_it(d, year=False)} — [giornata](../{d.year}/{d.isoformat()}.md)", ""]
        for x in by_day[d]:
            vote = {1: " 👍", -1: " 👎"}.get(state["ratings"].get(x.get("id")), "")
            out.append(f"- {labels.get(x['cat'], x['cat'])}: {x['title']}{vote}")
        out.append("")
    folder = ARCHIVE_DIR / "settimane"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{year}-W{week:02d}.md").write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


# ----------------------------------------------------------------------------
# Programma principale
# ----------------------------------------------------------------------------

def main():
    state = load_state()
    if not should_send(state):
        print("Fuori dalla finestra di invio (Milano) oppure già inviato oggi, esco.")
        return 0

    today = datetime.now(TZ).date()
    weekly = today.weekday() == 6
    process_feedback(state)

    todays = todays_categories(today)
    send_text(greeting(today, state, todays, weekly))

    failures, sections = [], []
    for cat in todays:
        time.sleep(PAUSE)
        try:
            needs_search = bool(cat.get("needs_search"))
            data = call_gemini(build_prompt(cat, state, today),
                               grounded=GROUNDING or needs_search, require_search=needs_search)
            if needs_search and not data.get("_sources"):
                raise RuntimeError("nessuna fonte web: il risultato non è verificabile")
            entry_id = f"{today:%Y%m%d}-{cat['id']}"
            image = None
            if cat.get("image") and data.get("image_query"):
                image = send_image(cat, str(data["image_query"]))
            data["_image"] = image
            data["_sources"] = resolve_sources(data.get("_sources", []))
            link, link_label = resolve_link(cat, data, image["title"] if image else None)
            send_card(cat, format_message(cat, data, today), entry_id, link, link_label)
            entry = {
                "id": entry_id, "date": today.isoformat(), "cat": cat["key"],
                "key": str(data["key"]), "title": str(data["title"]),
                "recap": str(data.get("recap") or data["subtitle"]),
            }
            state["log"] = [x for x in state["log"] if x.get("id") != entry_id] + [entry]
            sections.append(entry_markdown(cat, data, link, link_label))
            print(f"OK: {cat['key']}")
        except Exception as exc:  # una categoria che fallisce non blocca le altre
            failures.append(cat["label"])
            print(f"ERRORE su {cat['key']}: {exc}", file=sys.stderr)

    # Quiz a intervalli (la domenica, su tutta la settimana)
    questions = []
    try:
        items = pick_review_items(state, today, weekly)
        if items:
            time.sleep(PAUSE)
            questions = clean_questions(generate_review(items))
            if questions:
                send_quiz(questions, today, weekly)
                print("OK: quiz")
    except Exception as exc:
        failures.append("Quiz")
        print(f"ERRORE nel quiz: {exc}", file=sys.stderr)

    try:
        archive_day(today, sections, questions, weekly)
        archive_week(state, today)
    except Exception as exc:
        print(f"Archivio non aggiornato: {exc}", file=sys.stderr)

    if len(failures) < len(todays):
        state["_last_sent"] = today.isoformat()
    save_state(state)

    if failures:
        try:
            send_text("⚠️ Oggi non sono riuscito a generare: " + ", ".join(failures))
        except Exception as exc:
            print(f"Impossibile avvisare su Telegram: {exc}", file=sys.stderr)
    return 1 if len([f for f in failures if f != "Quiz"]) == len(todays) else 0


if __name__ == "__main__":
    sys.exit(main())
