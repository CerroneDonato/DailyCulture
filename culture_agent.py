"""Agente quotidiano di cultura generale: Gemini genera, Telegram consegna."""

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
HISTORY_KEEP = 150  # quante proposte passate ricordare
SEND_HOUR = 7  # ora locale (Milano) di invio
TZ = ZoneInfo("Europe/Rome")

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

SYSTEM = """Sei un curatore di cultura generale per un lettore adulto, curioso e colto.
Ogni giorno proponi cinque cose legate da un filo conduttore: un libro, una poesia,
un quadro, un brano musicale e tre parole nuove. Scrivi in italiano, con tono
sobrio e stimolante. Ogni "why" deve essere di 1-2 frasi concrete (contesto,
perché vale la pena), senza retorica.

Regole:
- Per la poesia riporta un estratto (max 4 versi) SOLO se l'autore è morto da più
  di 70 anni; altrimenti lascia "excerpt" vuoto e commenta soltanto.
- Le tre parole devono essere italiane, poco comuni ma non inventate, con
  significato breve e una frase d'esempio.
- Usa opere realmente esistenti. Se non sei sicuro, scegline un'altra.

Rispondi SOLO con JSON valido, senza testo extra, con questo schema:
{
  "theme": "filo conduttore in poche parole",
  "book": {"title": "", "author": "", "why": ""},
  "poem": {"title": "", "author": "", "excerpt": "", "why": ""},
  "painting": {"title": "", "artist": "", "year": "", "why": ""},
  "music": {"title": "", "artist": "", "why": ""},
  "words": [{"word": "", "meaning": "", "example": ""}]
}"""


def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return []


def save_history(history):
    HISTORY_FILE.write_text(
        json.dumps(history[-HISTORY_KEEP:], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


def should_send():
    """GitHub usa l'ora UTC: due cron coprono ora legale e solare, qui filtriamo."""
    if os.getenv("FORCE"):
        return True
    return datetime.now(TZ).hour == SEND_HOUR


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
        r = requests.post(url, headers=headers, json=body, timeout=60)
        if r.status_code in (429, 500, 503):
            time.sleep(15 * (attempt + 1))
            continue
        if r.status_code == 404:
            raise LookupError(model)
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```")
        return json.loads(text)
    raise RuntimeError(f"Gemini ({model}) non risponde dopo 4 tentativi")


def call_gemini(prompt):
    for model in MODELS:
        try:
            data = call_model(model, prompt)
            print(f"Modello usato: {model}")
            return data
        except LookupError:
            print(f"Modello non trovato (404): {model}, provo il successivo")
    raise RuntimeError(f"Nessun modello disponibile tra: {', '.join(MODELS)}")


def build_prompt(history):
    today = datetime.now(TZ).strftime("%A %d %B %Y")
    epoch, area = random.choice(EPOCHS), random.choice(AREAS)
    seen = "; ".join(history[-HISTORY_KEEP:]) or "nessuna"
    return (
        f"Oggi è {today}. Scegli un filo conduttore e prepara le cinque proposte.\n"
        f"Vincoli di varietà: almeno una proposta deve riguardare {epoch}; "
        f"almeno una deve provenire da questa area: {area}.\n"
        f"NON riproporre nulla di ciò che è già stato dato: {seen}"
    )


def q(*parts):
    return urllib.parse.quote_plus(" ".join(parts))


def format_message(d):
    e = html.escape
    book, poem, art, mus = d["book"], d["poem"], d["painting"], d["music"]

    art_link = "https://commons.wikimedia.org/w/index.php?search=" + q(art["title"], art["artist"])
    mus_link = "https://www.youtube.com/results?search_query=" + q(mus["title"], mus["artist"])

    lines = [
        f"🗓 <b>{e(d['theme'])}</b>",
        "",
        f"📚 <b>Libro</b>: {e(book['title'])}, {e(book['author'])}",
        e(book["why"]),
        "",
        f"🖋 <b>Poesia</b>: {e(poem['title'])}, {e(poem['author'])}",
    ]
    if poem.get("excerpt"):
        lines.append(f"<i>{e(poem['excerpt'])}</i>")
    lines += [
        e(poem["why"]),
        "",
        f"🎨 <b>Quadro</b>: {e(art['title'])}, {e(art['artist'])} ({e(str(art['year']))})",
        e(art["why"]),
        f'<a href="{html.escape(art_link)}">Vedi l\'opera</a>',
        "",
        f"🎵 <b>Musica</b>: {e(mus['title'])}, {e(mus['artist'])}",
        e(mus["why"]),
        f'<a href="{html.escape(mus_link)}">Ascolta</a>',
        "",
        "🔤 <b>Parole nuove</b>",
    ]
    for w in d["words"]:
        lines.append(f"• <b>{e(w['word'])}</b>: {e(w['meaning'])} <i>{e(w['example'])}</i>")
    return "\n".join(lines)


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
    if not should_send():
        print("Non è l'ora giusta (Milano), esco.")
        return 0

    history = load_history()
    data = call_gemini(build_prompt(history))
    send_telegram(format_message(data))

    history += [
        f"libro: {data['book']['title']} - {data['book']['author']}",
        f"poesia: {data['poem']['title']} - {data['poem']['author']}",
        f"quadro: {data['painting']['title']} - {data['painting']['artist']}",
        f"musica: {data['music']['title']} - {data['music']['artist']}",
    ] + [f"parola: {w['word']}" for w in data["words"]]
    save_history(history)
    return 0


if __name__ == "__main__":
    sys.exit(main())
