"""Agente quotidiano di cultura generale.

Ogni giorno genera con Gemini sei approfondimenti (letteratura, storia, arte,
musica, scienze, parole) e li manda su Telegram, un messaggio per categoria.
"""

import html
import json
import os
import random
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# Modelli provati in ordine: se uno risponde 404 (ritirato) si passa al successivo.
MODELS = (
    [os.environ["GEMINI_MODEL"]]
    if os.getenv("GEMINI_MODEL")
    else ["gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash"]
)
HISTORY_FILE = Path("history.json")
HISTORY_KEEP = 60  # argomenti ricordati per categoria
SEND_HOUR = 7  # ora locale (Milano) da cui l'invio è ammesso
SEND_UNTIL = 11  # ...fino a quest'ora esclusa (tollera i ritardi di GitHub)
TZ = ZoneInfo("Europe/Rome")
PAUSE = 6  # secondi tra una categoria e l'altra (limiti di frequenza del piano free)

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


def era_area():
    return f"epoca: {random.choice(EPOCHS)}; area geografica: {random.choice(AREAS)}"


CATEGORIES = [
    {
        "key": "letteratura", "emoji": "📚", "label": "Letteratura",
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
        "key": "storia", "emoji": "🏛", "label": "Storia",
        "level": NICHE, "hint": era_area, "link": "wiki", "link_label": "Approfondisci",
        "brief": (
            "Proponi UN episodio, processo o figura storica poco noti al grande pubblico "
            "(non le grandi date da manuale). Nei paragrafi: 1) contesto; 2) cosa è successo, "
            "con date e luoghi precisi; 3) cause e conseguenze; 4) perché è istruttivo o come "
            "cambia il modo di leggere il periodo."
        ),
    },
    {
        "key": "arte", "emoji": "🎨", "label": "Arte",
        "level": POPULAR, "hint": era_area, "link": "commons", "link_label": "Vedi l'opera",
        "brief": (
            "Proponi UN'opera d'arte visiva (pittura, scultura, architettura, fotografia, "
            "incisione). Nei paragrafi: 1) autore e contesto; 2) descrizione dell'opera "
            "(soggetto, composizione, tecnica, dove si trova); 3) come leggerla (simboli, "
            "innovazioni); 4) perché conta e a quali altre opere si collega."
        ),
    },
    {
        "key": "musica", "emoji": "🎵", "label": "Musica",
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
        "key": "scienze", "emoji": "🔬", "label": "Scienze",
        "level": NICHE,
        "hint": lambda: f"ambito: {random.choice(SCIENCE_FIELDS)}",
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
        "key": "parole", "emoji": "🔤", "label": "Parole",
        "level": NICHE,
        "hint": lambda: f"tipologia: {random.choice(WORD_KINDS)}",
        "link": "treccani", "link_label": "Vocabolario Treccani",
        "brief": (
            "Proponi TRE parole italiane poco comuni (non inventate). Un paragrafo per "
            "parola: la parola in apertura, significato preciso, etimologia (lingua d'origine "
            "e forma originale solo se certe), sfumature d'uso, una frase d'esempio originale. "
            "Un eventuale quarto paragrafo può collegare le tre parole, solo se c'è un legame "
            "reale. Il campo \"title\" contiene le tre parole separate da virgole; il campo "
            "\"search\" contiene la prima parola, una sola."
        ),
    },
]

SYSTEM = """Sei un curatore di cultura generale per un lettore adulto, ingegnere, colto e curioso.
Scrivi in italiano, con tono sobrio e denso, senza retorica e senza elenchi puntati.

Precisione prima di tutto: non inventare date, nomi, titoli o citazioni. Se non sei
sicuro di un dettaglio, omettilo oppure scegli un altro argomento. Non riportare
citazioni testuali lunghe di opere protette da diritti.

Lunghezza: 4-5 paragrafi, circa 250-350 parole in totale (massimo 3500 caratteri).

Rispondi SOLO con JSON valido, senza testo extra, con questo schema:
{
  "title": "argomento in poche parole",
  "subtitle": "una riga che incuriosisce",
  "paragraphs": ["paragrafo 1", "paragrafo 2"],
  "key": "identificativo breve dell'argomento per lo storico (es. 'Autore - Titolo')",
  "search": "query di ricerca per approfondire"
}"""


def load_history():
    if not HISTORY_FILE.exists():
        return {}
    data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    if isinstance(data, list):  # vecchio formato, valido per tutte le categorie
        return {"vecchio": data}
    return data


def save_history(history):
    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def should_send(history):
    """GitHub usa l'ora UTC e può ritardare: più cron, qui scegliamo quale vale.

    Si invia se a Milano è dentro la finestra 7-11 e oggi non è ancora partito nulla.
    """
    if os.getenv("FORCE"):
        return True
    now = datetime.now(TZ)
    if not (SEND_HOUR <= now.hour < SEND_UNTIL):
        return False
    return history.get("_last_sent") != now.date().isoformat()


def call_model(model, prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 1.0,
            "responseMimeType": "application/json",
        },
    }
    headers = {"x-goog-api-key": os.environ["GEMINI_API_KEY"]}
    for attempt in range(4):
        r = requests.post(url, headers=headers, json=body, timeout=90)
        if r.status_code in (429, 500, 503):
            time.sleep(15 * (attempt + 1))
            continue
        if r.status_code == 404:
            raise LookupError(model)
        r.raise_for_status()
        try:
            parts = r.json()["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```")
            data = json.loads(text)
            for field in ("title", "subtitle", "paragraphs", "key"):
                if field not in data:
                    raise KeyError(field)
            return data
        except (KeyError, IndexError, ValueError):
            time.sleep(5)  # risposta malformata: riprovo
    raise RuntimeError(f"Gemini ({model}) non ha dato una risposta valida")


def call_gemini(prompt):
    for model in MODELS:
        try:
            data = call_model(model, prompt)
            print(f"Modello usato: {model}")
            return data
        except LookupError:
            print(f"Modello non trovato (404): {model}, provo il successivo")
    raise RuntimeError(f"Nessun modello disponibile tra: {', '.join(MODELS)}")


def build_prompt(cat, history):
    today = datetime.now(TZ).strftime("%d/%m/%Y")
    seen = (history.get(cat["key"], []) + history.get("vecchio", []))[-HISTORY_KEEP:]
    seen_text = "; ".join(seen) or "nessuno"
    return (
        f"Oggi è il {today}. Prepara il messaggio di oggi per la categoria "
        f"«{cat['label']}».\n{cat['brief']}\n{cat['level']}\n"
        f"Spunto di varietà (non vincolante se non trovi nulla di certo): {cat['hint']()}\n"
        f"NON riproporre argomenti già dati: {seen_text}"
    )


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


def format_message(cat, d):
    e = html.escape
    link = make_link(cat, str(d.get("search") or d["title"]))
    head = (
        f"{cat['emoji']} <b>{cat['label'].upper()}</b>\n"
        f"<b>{e(str(d['title']))}</b>\n<i>{e(str(d['subtitle']))}</i>"
    )
    tail = f'<a href="{e(link)}">{cat["link_label"]}</a>'
    paras = [e(str(p)) for p in d["paragraphs"]]
    while True:  # Telegram accetta al massimo 4096 caratteri
        text = "\n\n".join([head] + paras + [tail])
        if len(text) <= 4000 or len(paras) <= 1:
            return text
        paras.pop()


def send_telegram(text):
    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage"
    r = requests.post(
        url,
        json={
            "chat_id": os.environ["TELEGRAM_CHAT_ID"],
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    r.raise_for_status()


def main():
    history = load_history()
    if not should_send(history):
        print("Fuori dalla finestra di invio (Milano) oppure già inviato oggi, esco.")
        return 0

    failures = []
    for i, cat in enumerate(CATEGORIES):
        if i:
            time.sleep(PAUSE)
        try:
            data = call_gemini(build_prompt(cat, history))
            send_telegram(format_message(cat, data))
            entries = history.setdefault(cat["key"], [])
            entries.append(str(data["key"]))
            history[cat["key"]] = entries[-HISTORY_KEEP:]
            print(f"OK: {cat['key']}")
        except Exception as exc:  # una categoria che fallisce non blocca le altre
            failures.append(cat["label"])
            print(f"ERRORE su {cat['key']}: {exc}", file=sys.stderr)

    if len(failures) < len(CATEGORIES):
        history["_last_sent"] = datetime.now(TZ).date().isoformat()
    save_history(history)

    if failures:
        try:
            send_telegram("⚠️ Oggi non sono riuscito a generare: " + ", ".join(failures))
        except Exception as exc:
            print(f"Impossibile avvisare su Telegram: {exc}", file=sys.stderr)
    return 1 if len(failures) == len(CATEGORIES) else 0


if __name__ == "__main__":
    sys.exit(main())
