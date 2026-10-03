"""Agente quotidiano di cultura generale.

Ogni mattina genera con Gemini (ancorato alla ricerca Google) sei approfondimenti
fissi più uno a rotazione secondo il giorno della settimana, li manda su Telegram
con bottoni 👍/👎, aggiunge un ripasso a intervalli e archivia tutto in Markdown.
"""

import html
import json
import os
import random
import re
import sys
import time
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
UA = "DailyCultureBot/1.0 (progetto personale; https://github.com/CerroneDonato/DailyCulture)"

GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MESI = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
    "agosto", "settembre", "ottobre", "novembre", "dicembre",
]

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
SCIENCE_FIELDS = [
    "matematica", "fisica", "chimica", "biologia ed evoluzione", "astronomia e cosmologia",
    "geologia e scienze della Terra", "storia della scienza", "teoria dell'informazione",
    "storia dell'ingegneria e delle tecnologie", "neuroscienze", "ecologia",
    "scienza dei materiali", "statistica e probabilità", "medicina e fisiologia",
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
    "oppure nome del luogo o dell'edificio), nella lingua originale."
)


def era_area():
    return f"epoca: {random.choice(EPOCHS)}; area geografica: {random.choice(AREAS)}"


# Categorie fisse (weekday assente) e categorie a rotazione (weekday 0=lunedì ... 6=domenica).
CATEGORIES = [
    {
        "key": "letteratura", "id": "let", "emoji": "📚", "label": "Letteratura",
        "level": NICHE, "hint": era_area, "link": "wiki", "link_label": "Approfondisci",
        "brief": (
            "Proponi UN'opera letteraria (romanzo, racconto, saggio, raccolta di poesie, "
            "poema) oppure un autore trascurato. Nei paragrafi: 1) autore e contesto in cui "
            "nasce l'opera; 2) di cosa parla e qual è l'idea o la tesi centrale; 3) perché è "
            "notevole (stile, innovazione, influenza); 4) a chi parla e da dove cominciare. "
            "Se citi versi, al massimo 4 e solo di autori morti da oltre 70 anni."
        ),
    },
    {
        "key": "storia", "id": "sto", "emoji": "🏛", "label": "Storia",
        "level": NICHE, "hint": era_area, "link": "wiki", "link_label": "Approfondisci",
        "brief": (
            "Proponi UN episodio, processo o figura storica poco noti al grande pubblico "
            "(non le grandi date da manuale). Nei paragrafi: 1) contesto; 2) cosa è successo, "
            "con date e luoghi precisi; 3) cause e conseguenze; 4) perché è istruttivo o come "
            "cambia il modo di leggere il periodo."
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
        "key": "musica", "id": "mus", "emoji": "🎵", "label": "Musica",
        "level": POPULAR, "hint": era_area, "link": "youtube", "link_label": "Ascolta",
        "brief": (
            "Proponi UN brano o un'opera musicale (qualsiasi genere: classica, jazz, rock, "
            "elettronica, folk...). Nei paragrafi: 1) autore o ensemble e contesto; 2) com'è "
            "fatto il brano (forma, armonia, ritmo, timbro) con dettagli tecnici; 3) cosa "
            "ascoltare con attenzione e in quale punto; 4) influenza e una curiosità sulla "
            "registrazione o versione consigliata."
        ),
    },
    {
        "key": "scienze", "id": "sci", "emoji": "🔬", "label": "Scienze",
        "level": NICHE, "hint": lambda: f"ambito: {random.choice(SCIENCE_FIELDS)}",
        "link": "wiki", "link_label": "Approfondisci",
        "brief": (
            "Proponi UN concetto, scoperta, esperimento o controversia scientifica. Il lettore "
            "ha formazione tecnica: puoi usare formule e ordini di grandezza, ma spiega "
            "l'intuizione, non solo il formalismo. Nei paragrafi: 1) il problema; 2) l'idea "
            "chiave; 3) come funziona o come fu scoperta; 4) implicazioni, limiti o questioni "
            "ancora aperte."
        ),
    },
    {
        "key": "parole", "id": "par", "emoji": "🔤", "label": "Parole",
        "level": NICHE, "hint": lambda: f"tipologia: {random.choice(WORD_KINDS)}",
        "link": "treccani", "link_label": "Vocabolario Treccani",
        "brief": (
            "Proponi TRE parole poco comuni, non inventate (di norma italiane; se la tipologia "
            "suggerita lo prevede, di altre lingue). Un paragrafo per parola: la parola in "
            "apertura, significato preciso, etimologia (lingua d'origine e forma originale "
            "solo se certe), sfumature d'uso, una frase d'esempio originale. Un eventuale "
            "quarto paragrafo può collegare le tre parole, solo se c'è un legame reale. Il "
            "campo \"title\" contiene le tre parole separate da virgole; il campo \"search\" "
            "contiene la prima parola, una sola."
        ),
    },
    # --- a rotazione ---
    {
        "key": "filosofia", "id": "fil", "emoji": "💭", "label": "Filosofia", "weekday": 0,
        "level": NICHE, "hint": era_area, "link": "wiki", "link_label": "Approfondisci",
        "brief": (
            "Proponi UN'idea, un argomento o un filosofo (anche non occidentale o poco "
            "frequentato). Nei paragrafi: 1) il problema da cui nasce; 2) la tesi centrale e "
            "la struttura dell'argomento; 3) le obiezioni principali e le repliche; 4) perché "
            "interessa oggi e da dove cominciare a leggere."
        ),
    },
    {
        "key": "cinema", "id": "cin", "emoji": "🎬", "label": "Cinema", "weekday": 1,
        "level": POPULAR, "hint": era_area, "link": "wiki", "link_label": "Approfondisci",
        "brief": (
            "Proponi UN film (anche non anglofono, muto, documentario o d'animazione). Nei "
            "paragrafi: 1) regista e contesto di produzione; 2) la trama in breve, senza "
            "rivelare il finale; 3) le scelte formali (inquadrature, montaggio, suono) che lo "
            "rendono notevole; 4) l'influenza e dove inserirlo in un percorso di visione."
        ),
    },
    {
        "key": "architettura", "id": "arc", "emoji": "🏗", "label": "Architettura",
        "weekday": 2, "image": True,
        "level": POPULAR, "hint": era_area, "link": "commons", "link_label": "Vedi le immagini",
        "brief": (
            "Proponi UN edificio, un'opera di ingegneria civile o un'idea urbanistica. Nei "
            "paragrafi: 1) autore, committente e contesto; 2) descrizione e soluzioni "
            "strutturali o formali; 3) i problemi tecnici affrontati e come furono risolti; "
            "4) l'eredità e dove vederlo." + IMAGE_NOTE
        ),
    },
    {
        "key": "ingegneria", "id": "ing", "emoji": "⚙️", "label": "Ingegneria", "weekday": 3,
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
        "key": "economia", "id": "eco", "emoji": "📈", "label": "Economia e società",
        "weekday": 4,
        "level": NICHE, "hint": era_area, "link": "wiki", "link_label": "Approfondisci",
        "brief": (
            "Proponi UN concetto, episodio o pensatore di economia e scienze sociali (storia "
            "economica, teoria dei giochi, istituzioni, demografia). Nei paragrafi: 1) la "
            "domanda di partenza; 2) il modello o l'evidenza; 3) casi concreti e limiti; "
            "4) le implicazioni."
        ),
    },
    {
        "key": "geografia", "id": "geo", "emoji": "🌍", "label": "Geografia", "weekday": 5,
        "image": True,
        "level": NICHE, "hint": lambda: f"area: {random.choice(AREAS)}",
        "link": "wiki", "link_label": "Approfondisci",
        "brief": (
            "Proponi UN luogo, un fenomeno geografico o geologico, oppure una peculiarità "
            "culturale di un territorio poco noto. Nei paragrafi: 1) dove si trova e cos'è; "
            "2) come si è formato o la sua storia; 3) le caratteristiche sorprendenti, con "
            "dati; 4) perché è significativo." + IMAGE_NOTE
        ),
    },
    {
        "key": "saggio", "id": "sag", "emoji": "✍️", "label": "Il saggio della domenica",
        "weekday": 6, "length": "6-7 paragrafi, circa 450-550 parole (massimo 3300 caratteri)",
        "level": NICHE,
        "hint": lambda: "ambito a scelta tra " + ", ".join(
            random.sample(["scienza", "storia", "letteratura", "filosofia", "arte", "tecnologia", "lingua"], 3)
        ),
        "link": "wiki", "link_label": "Approfondisci",
        "brief": (
            "Scrivi un breve saggio su un tema libero e stimolante, con una tesi chiara, "
            "esempi concreti e una conclusione che apra una domanda. Tono da saggista."
        ),
    },
]
CORE = [c for c in CATEGORIES if c.get("weekday") is None]
ROTATING = {c["weekday"]: c for c in CATEGORIES if c.get("weekday") is not None}

SYSTEM = """Sei un curatore di cultura generale per un lettore adulto, ingegnere, colto e curioso.
Scrivi in italiano, con tono sobrio e denso, senza retorica e senza elenchi puntati.

Precisione prima di tutto: non inventare date, nomi, titoli o citazioni. Se non sei
sicuro di un dettaglio, omettilo oppure scegli un altro argomento. Se hai accesso alla
ricerca web, usala per verificare i fatti. Non riportare citazioni testuali lunghe di
opere protette da diritti.

Rispondi SOLO con un oggetto JSON valido, senza testo prima o dopo e senza blocchi di
codice, con questo schema:
{
  "title": "argomento in poche parole",
  "subtitle": "una riga che incuriosisce",
  "paragraphs": ["paragrafo 1", "paragrafo 2"],
  "recap": "2-3 frasi con i fatti chiave da ricordare (nomi, date, numeri), comprensibili da sole",
  "key": "identificativo breve dell'argomento per lo storico (es. 'Autore - Titolo')",
  "search": "query di ricerca per approfondire",
  "image_query": "solo se richiesto, altrimenti stringa vuota"
}"""

REVIEW_SYSTEM = """Sei un tutor che prepara domande di ripasso per un lettore adulto, ingegnere.
Ricevi alcune schede (categoria, titolo, riassunto dei fatti chiave). Per OGNI scheda
scrivi UNA domanda, basandoti SOLO sul riassunto della scheda. La domanda deve essere
comprensibile da sola (non scrivere "nel testo" o "nella scheda"), richiedere un fatto o
un ragionamento preciso e avere una risposta breve (massimo 2 frasi).

Rispondi SOLO con JSON valido, senza altro testo, con questo schema:
{"questions": [{"q": "domanda", "a": "risposta", "topic": "titolo della scheda"}]}"""

CONTENT_FIELDS = ("title", "subtitle", "paragraphs", "key")


# ----------------------------------------------------------------------------
# Utilità
# ----------------------------------------------------------------------------

def data_it(d, year=True):
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
            if isinstance(data.get("paragraphs"), str):
                data["paragraphs"] = [data["paragraphs"]]
            data["_sources"] = extract_sources(cand) if grounded else []
            return data
        except (KeyError, IndexError, ValueError, TypeError, AttributeError):
            time.sleep(5)  # risposta malformata: riprovo
    raise RuntimeError(f"Gemini ({model}) non ha dato una risposta valida")


def call_gemini(prompt, system=SYSTEM, grounded=GROUNDING, required=CONTENT_FIELDS):
    for model in MODELS:
        for use_search in ([True, False] if grounded else [False]):
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
    hint = cat["hint"]() if cat.get("hint") else ""
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
        try:
            tg("editMessageReplyMarkup", {
                "chat_id": msg["chat"]["id"],
                "message_id": msg["message_id"],
                "reply_markup": {"inline_keyboard": [[{"text": label, "callback_data": "noop"}]]},
            })
        except Exception:
            pass  # il voto è comunque registrato


def fetch_commons_image(query):
    """Cerca su Wikimedia Commons un'immagine pertinente; None se non è affidabile."""
    headers = {"User-Agent": UA}
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 8,
        "prop": "imageinfo", "iiprop": "url|size|mime", "iiurlwidth": 1280,
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
            return img.content, name
    return None


def send_image(cat, query):
    """Foto dell'opera/luogo prima del testo; qualsiasi problema = nessuna foto."""
    try:
        found = fetch_commons_image(query)
        if not found:
            return
        content, name = found
        caption = f"{cat['emoji']} <b>{esc(name[:180])}</b>\n<i>Wikimedia Commons</i>"
        tg("sendPhoto", {"chat_id": chat_id(), "caption": caption, "parse_mode": "HTML"},
           files={"photo": ("immagine.jpg", content)})
    except Exception as exc:
        print(f"Immagine non inviata: {exc}", file=sys.stderr)


# ----------------------------------------------------------------------------
# Formattazione dei messaggi
# ----------------------------------------------------------------------------

def make_link(cat, query):
    kind = cat["link"]
    if kind == "commons":
        return "https://commons.wikimedia.org/w/index.php?search=" + urllib.parse.quote_plus(query)
    if kind == "youtube":
        return "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
    if kind == "treccani":
        word = (query.split() or [""])[0].lower()
        return "https://www.treccani.it/vocabolario/ricerca/" + urllib.parse.quote(word) + "/"
    return "https://it.wikipedia.org/w/index.php?search=" + urllib.parse.quote_plus(query)


def format_message(cat, d, today, link):
    e = esc
    head = (
        f"{cat['emoji']} <b>{e(cat['label'].upper())}</b> · <i>{data_it(today, year=False)}</i>\n\n"
        f"<b>{e(str(d['title']))}</b>\n<i>{e(str(d['subtitle']))}</i>"
    )
    paras = [e(str(p)) for p in d["paragraphs"]]
    recap = f"<blockquote>📌 {e(str(d['recap']))}</blockquote>" if d.get("recap") else ""
    sources = ""
    if d.get("_sources"):
        sources = "🔎 " + " · ".join(f'<a href="{esc_attr(u)}">{e(t)}</a>' for t, u in d["_sources"])
    tail = f'👉 <a href="{esc_attr(link)}">{e(cat["link_label"])}</a>'

    def assemble():
        return "\n\n".join(x for x in [head, *paras, recap, sources, tail] if x)

    while len(assemble()) > 4000 and len(paras) > 1:  # limite Telegram: 4096 caratteri
        paras.pop()
    if len(assemble()) > 4000:
        sources = ""
    return assemble()


def pick_review_items(state, today, weekly):
    by_date = {}
    for x in state["log"]:
        if x.get("date") and x.get("recap"):
            by_date.setdefault(x["date"], []).append(x)
    plan = {d: 1 for d in range(1, 7)} if weekly else {1: 2, 3: 1, 7: 1, 14: 1}
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


def clean_questions(d):
    out = []
    for q in d.get("questions", []):
        if isinstance(q, dict) and q.get("q") and q.get("a"):
            out.append({"q": str(q["q"]), "a": str(q["a"]), "topic": str(q.get("topic", ""))})
    return out[:8]


def format_review(questions, today, weekly):
    e = esc
    title = "QUIZ DELLA DOMENICA" if weekly else "RIPASSO"
    intro = ("Domande sulle letture della settimana." if weekly
             else "Domande su ciò che hai letto 1, 3, 7 e 14 giorni fa.")
    lines = [
        f"🧠 <b>{title}</b> · <i>{data_it(today, year=False)}</i>",
        f"<i>{intro} Tocca il riquadro nascosto per vedere la risposta.</i>",
        "",
    ]
    for i, q in enumerate(questions, 1):
        lines.append(f"<b>{i}.</b> {e(q['q'])}")
        lines.append(f"<tg-spoiler>{e(q['a'])}</tg-spoiler>")
        lines.append("")
    text = "\n".join(lines).strip()
    return text[:4000]


# ----------------------------------------------------------------------------
# Archivio Markdown
# ----------------------------------------------------------------------------

def entry_markdown(cat, d, link):
    lines = [f"## {cat['emoji']} {cat['label']}: {d['title']}", "", f"*{d['subtitle']}*", ""]
    for p in d["paragraphs"]:
        lines += [str(p), ""]
    if d.get("recap"):
        lines += [f"> 📌 {d['recap']}", ""]
    lines.append(f"[{cat['link_label']}]({link})")
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
        out += ["## 🧠 " + ("Quiz della domenica" if weekly else "Ripasso"), ""]
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

    todays = CORE + [ROTATING[today.weekday()]]
    send_text(
        f"☀️ <b>Cultura del giorno</b>\n<i>{data_it(today)}</i>\n\n"
        f"Tema della settimana: <b>{esc(week_theme(today))}</b>\n"
        "Oggi: " + ", ".join(c["label"] for c in todays) + " e un " +
        ("quiz" if weekly else "ripasso") + "."
    )

    failures, sections = [], []
    for cat in todays:
        time.sleep(PAUSE)
        try:
            data = call_gemini(build_prompt(cat, state, today))
            link = make_link(cat, str(data.get("search") or data["title"]))
            entry_id = f"{today:%Y%m%d}-{cat['id']}"
            if cat.get("image") and data.get("image_query"):
                send_image(cat, str(data["image_query"]))
            send_text(format_message(cat, data, today, link), markup=vote_buttons(entry_id))
            entry = {
                "id": entry_id, "date": today.isoformat(), "cat": cat["key"],
                "key": str(data["key"]), "title": str(data["title"]),
                "recap": str(data.get("recap") or data["subtitle"]),
            }
            state["log"] = [x for x in state["log"] if x.get("id") != entry_id] + [entry]
            sections.append(entry_markdown(cat, data, link))
            print(f"OK: {cat['key']}")
        except Exception as exc:  # una categoria che fallisce non blocca le altre
            failures.append(cat["label"])
            print(f"ERRORE su {cat['key']}: {exc}", file=sys.stderr)

    # Ripasso a intervalli (o quiz settimanale la domenica)
    questions = []
    try:
        items = pick_review_items(state, today, weekly)
        if items:
            time.sleep(PAUSE)
            questions = clean_questions(generate_review(items))
            if questions:
                send_text(format_review(questions, today, weekly))
                print("OK: ripasso")
    except Exception as exc:
        failures.append("Ripasso")
        print(f"ERRORE nel ripasso: {exc}", file=sys.stderr)

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
    return 1 if len([f for f in failures if f != "Ripasso"]) == len(todays) else 0


if __name__ == "__main__":
    sys.exit(main())
