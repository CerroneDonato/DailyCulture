import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Article } from "./archive";

export type ArticleImage = {
  src: string;
  width: number;
  height: number;
  credit: string;
  creditUrl: string;
};

const currentFile = fileURLToPath(import.meta.url);
const siteRoot = path.resolve(path.dirname(currentFile), "../..");
const cacheFile = path.join(siteRoot, ".cache", "images.json");

const UA = "DailyCultureSite/1.0 (progetto personale; https://github.com/CerroneDonato/DailyCulture)";
const THUMB = 1280;
const MIN_WIDTH = 400;
const DISABLED = process.env.NO_IMAGES === "1";

type CacheEntry = ArticleImage | null;

let diskCache: Record<string, CacheEntry> | null = null;
const pending = new Map<string, Promise<CacheEntry>>();

function loadCache(): Record<string, CacheEntry> {
  if (diskCache) return diskCache;
  try {
    diskCache = JSON.parse(fs.readFileSync(cacheFile, "utf-8"));
  } catch {
    diskCache = {};
  }
  return diskCache!;
}

function saveCache() {
  try {
    fs.mkdirSync(path.dirname(cacheFile), { recursive: true });
    fs.writeFileSync(cacheFile, JSON.stringify(diskCache, null, 1));
  } catch {
    // la cache è facoltativa
  }
}

// Le richieste a Wikimedia sono serializzate a piccoli gruppi per non farsi limitare.
let active = 0;
const queue: (() => void)[] = [];
async function limited<T>(fn: () => Promise<T>): Promise<T> {
  if (active >= 2) await new Promise<void>((resolve) => queue.push(resolve));
  active += 1;
  try {
    return await fn();
  } finally {
    active -= 1;
    queue.shift()?.();
  }
}

async function getJson(url: string): Promise<any> {
  return limited(async () => {
    for (let attempt = 0; ; attempt += 1) {
      const res = await fetch(url, { headers: { "User-Agent": UA }, signal: AbortSignal.timeout(12000) });
      if (res.ok) return res.json();
      if ((res.status !== 429 && res.status < 500) || attempt >= 3) throw new Error(`${res.status} ${url}`);
      await new Promise((r) => setTimeout(r, 1500 * 2 ** attempt));
    }
  });
}

function normalize(text: string): string {
  return text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

function tokens(text: string): string[] {
  return [...new Set(normalize(text).match(/[a-z0-9]{4,}/g) ?? [])];
}

/** Le parole del titolo della pagina trovata compaiono nell'articolo (tutte, se sono una o due). */
function relevant(pageTitle: string, haystack: string): boolean {
  const words = tokens(pageTitle.replace(/^File:/, "").replace(/\.[a-z]{3,4}$/i, ""));
  if (!words.length) return false;
  const hits = words.filter((w) => haystack.includes(w)).length;
  return hits >= Math.max(Math.ceil(words.length / 2), Math.min(words.length, 2));
}

const STOPWORDS = new Set(
  ("della delle dello degli nella nelle negli dalla dalle dagli sulla sulle questo questa questi sono anche " +
    "come dopo prima molto essere stato stata viene the with from that this which were their about after").split(" "),
);

/** L'incipit della voce trovata condivide almeno una parola significativa con l'articolo. */
function sameSubject(extract: string, pageTitle: string, haystack: string): boolean {
  const own = new Set(tokens(pageTitle));
  return tokens(extract).some((w) => w.length >= 5 && !own.has(w) && !STOPWORDS.has(w) && haystack.includes(w));
}

function api(host: string, params: Record<string, string | number>): string {
  const qs = new URLSearchParams({ format: "json", formatversion: "2", ...Object.fromEntries(
    Object.entries(params).map(([k, v]) => [k, String(v)]),
  ) });
  return `https://${host}/w/api.php?${qs}`;
}

function stripHtml(input: string): string {
  return input.replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
}

async function fromCommonsFile(fileTitle: string): Promise<CacheEntry> {
  const data = await getJson(api("commons.wikimedia.org", {
    action: "query", titles: fileTitle, prop: "imageinfo",
    iiprop: "url|size|extmetadata", iiurlwidth: THUMB,
  }));
  const page = data?.query?.pages?.[0];
  const info = page?.imageinfo?.[0];
  if (!info?.thumburl || (info.thumbwidth ?? 0) < MIN_WIDTH || !usableFile(page.title ?? "")) return null;
  const artist = stripHtml(info.extmetadata?.Artist?.value ?? "");
  const license = stripHtml(info.extmetadata?.LicenseShortName?.value ?? "");
  return {
    src: info.thumburl,
    width: info.thumbwidth,
    height: info.thumbheight,
    credit: [artist, license, "Wikimedia Commons"].filter(Boolean).join(" · ").slice(0, 160),
    creditUrl: info.descriptionurl,
  };
}

// Bandiere, stemmi, loghi e cartine non illustrano bene un articolo.
const UNWANTED = /(^|[_\s(.,-])(flag|flags|bandiera|coat[_ ]of[_ ]arms|stemma|wappen|escudo|logo|emblem|seal|icon|location|locator|map|mappa|karte|blank)(?=$|[_\s).,-])/i;

function usableFile(name: string): boolean {
  if (/\.(ogv|webm|ogg|mp3|wav|pdf|tiff?)$/i.test(name)) return false;
  return !UNWANTED.test(name.replace(/\.[a-z0-9]+$/i, ""));
}

function pageImage(page: any, lang: string): CacheEntry {
  const thumb = page?.thumbnail;
  if (!thumb?.source || (thumb.width ?? 0) < MIN_WIDTH || !page.pageimage) return null;
  if (!usableFile(page.pageimage)) return null;
  return {
    src: thumb.source,
    width: thumb.width,
    height: thumb.height,
    credit: `Wikipedia (${lang}) · Wikimedia Commons`,
    creditUrl: `https://${lang}.wikipedia.org/wiki/File:${encodeURIComponent(page.pageimage)}`,
  };
}

async function fromWikipediaTitle(lang: string, title: string): Promise<CacheEntry> {
  const data = await getJson(api(`${lang}.wikipedia.org`, {
    action: "query", titles: title, redirects: 1,
    prop: "pageimages", piprop: "thumbnail|name", pithumbsize: THUMB,
  }));
  return pageImage(data?.query?.pages?.[0], lang);
}

async function fromWikipediaSearch(
  lang: string,
  query: string,
  haystack: string,
  fullText: string,
): Promise<CacheEntry> {
  const data = await getJson(api(`${lang}.wikipedia.org`, {
    action: "query", generator: "search", gsrsearch: query, gsrlimit: 5,
    prop: "pageimages|extracts", piprop: "thumbnail|name", pithumbsize: THUMB,
    exintro: 1, explaintext: 1, exsentences: 2, exlimit: 5,
  }));
  const pages = [...(data?.query?.pages ?? [])].sort((a, b) => (a.index ?? 99) - (b.index ?? 99));
  for (const page of pages) {
    if (!relevant(page.title, haystack)) continue;
    if (!sameSubject(page.extract ?? "", page.title, fullText)) continue;
    if (/\.svg$/i.test(page.pageimage ?? "")) continue;
    const image = pageImage(page, lang);
    if (image) return image;
  }
  return null;
}

const PERSON_ROLE = /autor|scritt|poet|compositor|music|regist|scopr|artist|pittor|scultor|architett|filosof|inventor|matematic|scienziat|fisic|propon|progettist|protagonist|ideator|fondator|teoric|pensator/i;

/** Persone citate nella scheda (autore, scopritore...): il loro ritratto è un buon ripiego. */
function peopleInFacts(article: Article): string[] {
  return article.facts
    .filter((f) => PERSON_ROLE.test(f.k))
    .map((f) => f.v.replace(/\(.*?\)/g, "").split(/[,;]| e /)[0].trim())
    .filter((v) => /^\p{Lu}/u.test(v) && !/\d/.test(v) && v.split(/\s+/).length >= 2 && v.split(/\s+/).length <= 5);
}

async function resolve(article: Article): Promise<CacheEntry> {
  // La pertinenza del titolo si misura su titolo, sottotitolo e scheda; l'incipit della voce sul testo intero.
  const haystack = normalize([article.title, article.subtitle, ...article.facts.map((f) => f.v)].join(" "));
  const fullText = normalize([haystack, ...article.paragraphs.map((p) => `${p.h} ${p.text}`)].join(" "));
  const url = article.link?.url ?? "";

  const commons = url.match(/commons\.wikimedia\.org\/wiki\/(File[:%].+)$/);
  if (commons) {
    const found = await fromCommonsFile(decodeURIComponent(commons[1]));
    if (found) return found;
  }

  const wiki = url.match(/https:\/\/(\w+)\.wikipedia\.org\/wiki\/(.+)$/);
  if (wiki) {
    const title = decodeURIComponent(wiki[2]).replaceAll("_", " ");
    if (relevant(title, haystack)) {
      const found = await fromWikipediaTitle(wiki[1], title);
      if (found) return found;
    }
  }

  const firstFact = article.facts[0]?.v ?? "";
  const queries = [article.title, `${article.title} ${firstFact}`.trim()];
  for (const lang of ["it", "en"]) {
    for (const query of queries) {
      const found = await fromWikipediaSearch(lang, query, haystack, fullText);
      if (found) return found;
    }
  }

  for (const name of peopleInFacts(article).slice(0, 2)) {
    for (const lang of ["it", "en"]) {
      const found = await fromWikipediaSearch(lang, name, normalize(name), fullText);
      if (found) return found;
    }
  }
  return null;
}

/** Immagine scelta dall'agente e salvata nell'archivio: nessuna ricerca necessaria. */
function savedImage(article: Article): ArticleImage | null {
  const saved = article.savedImage;
  if (!saved) return null;
  const filePath = saved.src.match(/\/wiki\/Special:FilePath\/([^?#]+)/);
  return {
    src: saved.src,
    width: 1280,
    height: 853,
    credit: saved.credit,
    creditUrl: filePath ? `https://commons.wikimedia.org/wiki/File:${filePath[1]}` : saved.src,
  };
}

export async function getArticleImage(article: Article): Promise<ArticleImage | null> {
  const saved = savedImage(article);
  if (saved) return saved;
  if (DISABLED || !article.category.withImage) return null;

  const cache = loadCache();
  const key = article.slug;
  if (key in cache) return cache[key];

  let job = pending.get(key);
  if (!job) {
    job = resolve(article)
      .catch((err) => {
        console.warn(`[immagini] ${article.slug}: ${err.message ?? err}`);
        return undefined as unknown as CacheEntry;
      })
      .then((image) => {
        if (image !== undefined) {
          cache[key] = image;
          saveCache();
        }
        return image ?? null;
      });
    pending.set(key, job);
  }
  return job;
}

export async function withImages<T extends Article>(articles: T[]): Promise<(T & { image: ArticleImage | null })[]> {
  const images = await Promise.all(articles.map((a) => getArticleImage(a)));
  return articles.map((a, i) => ({ ...a, image: images[i] }));
}
