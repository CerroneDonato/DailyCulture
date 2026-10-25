import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { marked } from "marked";

const currentFile = fileURLToPath(import.meta.url);
const siteRoot = path.resolve(path.dirname(currentFile), "../..");
const projectRoot = path.resolve(siteRoot, "..");
const archiveRoot = path.join(projectRoot, "archivio");

export type HistoryEntry = {
  id?: string;
  date?: string;
  cat?: string;
  key?: string;
  title?: string;
  recap?: string;
};

export type HistoryState = {
  _last_sent?: string;
  _offset?: number;
  log?: HistoryEntry[];
  ratings?: Record<string, number>;
};

export type Category = {
  key: string;
  id: string;
  label: string;
  short: string;
  emoji: string;
  color: string;
  withImage: boolean;
};

export type Paragraph = { h: string; html: string; text: string };
export type Fact = { k: string; v: string };
export type Link = { label: string; url: string };

export type Article = {
  slug: string;
  issueSlug: string;
  date: string;
  theme: string;
  category: Category;
  title: string;
  subtitle: string;
  facts: Fact[];
  paragraphs: Paragraph[];
  recap: string;
  challenge: string;
  solution: string;
  link: Link | null;
  sources: Link[];
  savedImage: { src: string; credit: string } | null;
  excerpt: string;
  readingMinutes: number;
  liked: boolean;
};

export type QuizItem = { q: string; a: string };

export type Issue = {
  slug: string;
  date: string;
  title: string;
  theme: string;
  number: number;
  articles: Article[];
  quiz: QuizItem[];
  quizTitle: string;
};

export type Week = {
  slug: string;
  label: string;
  theme: string;
  issues: Issue[];
};

// Stesse categorie di culture_agent.py (etichetta usata nell'intestazione Markdown).
const CATEGORY_LIST: Category[] = [
  { key: "letteratura", id: "let", label: "Letteratura", short: "Letteratura", emoji: "📚", color: "#7a2e2e", withImage: true },
  { key: "storia", id: "sto", label: "Storia", short: "Storia", emoji: "🏛", color: "#8a5a1f", withImage: true },
  { key: "arte", id: "art", label: "Arte", short: "Arte", emoji: "🎨", color: "#a3354f", withImage: true },
  { key: "musica", id: "mus", label: "Musica", short: "Musica", emoji: "🎵", color: "#5b3a8c", withImage: true },
  { key: "scienze", id: "sci", label: "Scienze", short: "Scienze", emoji: "🔬", color: "#1f5f8b", withImage: true },
  { key: "parole", id: "par", label: "Parole", short: "Parole", emoji: "🔤", color: "#4a4a4a", withImage: false },
  { key: "filosofia", id: "fil", label: "Filosofia", short: "Filosofia", emoji: "💭", color: "#3d4f7a", withImage: true },
  { key: "cinema", id: "cin", label: "Cinema", short: "Cinema", emoji: "🎬", color: "#262626", withImage: true },
  { key: "architettura", id: "arc", label: "Architettura", short: "Architettura", emoji: "🏗", color: "#6b5b45", withImage: true },
  { key: "ingegneria", id: "ing", label: "Ingegneria", short: "Ingegneria", emoji: "⚙️", color: "#2f5d50", withImage: true },
  { key: "economia", id: "eco", label: "Economia e società", short: "Economia", emoji: "📈", color: "#1d6b4f", withImage: true },
  { key: "geografia", id: "geo", label: "Geografia", short: "Geografia", emoji: "🌍", color: "#2a6f86", withImage: true },
  { key: "saggio", id: "sag", label: "Il saggio della domenica", short: "Saggio", emoji: "✍️", color: "#8c2f1b", withImage: true },
  { key: "matematica", id: "mat", label: "Matematica", short: "Matematica", emoji: "🧮", color: "#3b3f8f", withImage: true },
  { key: "ricerca", id: "ric", label: "Dalla ricerca", short: "Ricerca", emoji: "🔭", color: "#0f5c7a", withImage: true },
  { key: "natura", id: "nat", label: "Natura", short: "Natura", emoji: "🌿", color: "#3f6b2a", withImage: true },
  { key: "archeologia", id: "ant", label: "Archeologia", short: "Archeologia", emoji: "🏺", color: "#9a5b2e", withImage: true },
  { key: "cibo", id: "cib", label: "Cibo e cultura", short: "Cibo", emoji: "🍝", color: "#b0482a", withImage: true },
];

const CATEGORY_BY_LABEL = new Map(CATEGORY_LIST.map((c) => [c.label.toLowerCase(), c]));

export function getCategories(): Category[] {
  return CATEGORY_LIST;
}

export function getCategory(key: string): Category | undefined {
  return CATEGORY_LIST.find((c) => c.key === key);
}

function readTextSafe(filePath: string): string | null {
  try {
    return fs.readFileSync(filePath, "utf-8");
  } catch {
    return null;
  }
}

function listMarkdownFiles(dir: string): string[] {
  if (!fs.existsSync(dir)) return [];

  return fs
    .readdirSync(dir, { withFileTypes: true })
    .flatMap((entry) => {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) return listMarkdownFiles(fullPath);
      return entry.isFile() && entry.name.endsWith(".md") ? [fullPath] : [];
    })
    .sort();
}

export function stripMarkdown(input: string): string {
  return input
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1")
    .replace(/[*_`~]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  const cut = text.slice(0, max);
  return cut.slice(0, cut.lastIndexOf(" ")).replace(/[,;:.]$/, "") + "…";
}

export function slugify(input: string): string {
  return input
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
}

function inline(text: string): string {
  return marked.parseInline(text) as string;
}

function fallbackCategory(label: string, emoji: string): Category {
  const key = slugify(label) || "varie";
  return { key, id: key.slice(0, 3), label, short: label, emoji, color: "#555555", withImage: true };
}

function parseLinkLine(line: string): Link | null {
  const m = line.match(/^\[([^\]]+)\]\((\S+)\)$/);
  return m ? { label: m[1], url: m[2] } : null;
}

type RawSection = { header: string; lines: string[] };

function splitSections(body: string): RawSection[] {
  const sections: RawSection[] = [];
  let current: RawSection | null = null;
  for (const line of body.split(/\r?\n/)) {
    if (line.startsWith("## ")) {
      current = { header: line.slice(3).trim(), lines: [] };
      sections.push(current);
    } else if (current) {
      current.lines.push(line);
    }
  }
  return sections;
}

function parseQuiz(lines: string[]): QuizItem[] {
  const items: QuizItem[] = [];
  for (const line of lines) {
    const q = line.match(/^\d+\.\s+(.+)$/);
    if (q) {
      items.push({ q: q[1].trim(), a: "" });
      continue;
    }
    const a = line.match(/^\s+-\s+\*Risposta:\*\s*(.+)$/);
    if (a && items.length) items[items.length - 1].a = a[1].trim();
  }
  return items.filter((x) => x.q);
}

function parseArticle(
  section: RawSection,
  date: string,
  theme: string,
  ratings: Record<string, number>,
  usedSlugs: Set<string>,
): Article | null {
  const head = section.header.match(/^(\S+)\s+([^:]+?):\s+(.+)$/u);
  if (!head) return null;
  const [, emoji, label, title] = head;
  const category = CATEGORY_BY_LABEL.get(label.trim().toLowerCase()) ?? fallbackCategory(label.trim(), emoji);

  let subtitle = "";
  let recap = "";
  let challenge = "";
  let solution = "";
  let link: Link | null = null;
  let savedImage: Article["savedImage"] = null;
  const facts: Fact[] = [];
  const sources: Link[] = [];
  const paragraphs: { h: string; lines: string[] }[] = [];

  for (const raw of section.lines) {
    const line = raw.trim();
    if (!line) continue;

    const fact = line.match(/^-\s+\*\*(.+?):\*\*\s*(.+)$/);
    const source = line.match(/^-\s+Fonte:\s+\[([^\]]+)\]\((\S+)\)$/);
    const sub = line.match(/^\*([^*].*[^*])\*$/);
    const challengeLine = line.match(/^\*\*🧩 Prova tu:\*\*\s*(.+)$/u);
    const solutionLine = line.match(/^>\s*\*Soluzione:\*\s*(.+)$/);
    const recapLine = line.match(/^>\s*📌\s*(.+)$/u);
    const linkLine = parseLinkLine(line);
    const imageLine = line.match(/^!\[([^\]]*)\]\((https:\/\/\S+)\)$/);

    if (imageLine && !savedImage && !paragraphs.length) {
      savedImage = { src: imageLine[2], credit: imageLine[1].trim() || "Wikimedia Commons" };
    } else if (line.startsWith("### ")) {
      paragraphs.push({ h: line.slice(4).trim(), lines: [] });
    } else if (source) {
      sources.push({ label: source[1], url: source[2] });
    } else if (fact && !paragraphs.length) {
      facts.push({ k: fact[1], v: fact[2] });
    } else if (sub && !subtitle && !paragraphs.length) {
      subtitle = sub[1];
    } else if (challengeLine) {
      challenge = challengeLine[1];
    } else if (solutionLine) {
      solution = solutionLine[1];
    } else if (recapLine) {
      recap = recapLine[1];
    } else if (linkLine) {
      link = linkLine;
    } else {
      if (!paragraphs.length) paragraphs.push({ h: "", lines: [] });
      paragraphs[paragraphs.length - 1].lines.push(line);
    }
  }

  const rendered: Paragraph[] = paragraphs
    .map((p) => {
      const text = p.lines.join(" ").trim();
      return { h: p.h, html: inline(text), text: stripMarkdown(text) };
    })
    .filter((p) => p.text || p.h);

  const plain = rendered.map((p) => p.text).join(" ");
  const words = plain.split(/\s+/).filter(Boolean).length;
  const entryId = `${date.replaceAll("-", "")}-${category.id}`;

  let slug = `${date}-${category.key}`;
  for (let i = 2; usedSlugs.has(slug); i += 1) slug = `${date}-${category.key}-${i}`;
  usedSlugs.add(slug);

  return {
    slug,
    issueSlug: date,
    date,
    theme,
    category,
    title: title.trim(),
    subtitle,
    facts,
    paragraphs: rendered,
    recap,
    challenge,
    solution,
    link,
    sources,
    savedImage,
    excerpt: truncate(plain || subtitle, 220),
    readingMinutes: Math.max(1, Math.round(words / 200)),
    liked: ratings[entryId] === 1,
  };
}

let issuesCache: Issue[] | null = null;

export function getIssues(): Issue[] {
  if (issuesCache) return issuesCache;

  const ratings = getHistoryMeta().ratings ?? {};
  const files = listMarkdownFiles(archiveRoot).filter((f) => /\d{4}-\d{2}-\d{2}\.md$/.test(f));
  const usedSlugs = new Set<string>();

  const issues = files.flatMap((filePath): Issue[] => {
    const source = readTextSafe(filePath);
    if (!source) return [];

    const date = path.basename(filePath, ".md");
    const titleMatch = source.match(/^#\s+(.+)$/m);
    const themeMatch = source.match(/Tema della settimana:\s+\*(.+?)\*/m);
    const theme = themeMatch ? themeMatch[1].trim() : "";

    const articles: Article[] = [];
    let quiz: QuizItem[] = [];
    let quizTitle = "Quiz";
    for (const section of splitSections(source)) {
      if (section.header.startsWith("🧠")) {
        quiz = parseQuiz(section.lines);
        quizTitle = section.header.replace("🧠", "").trim() || quizTitle;
        continue;
      }
      const article = parseArticle(section, date, theme, ratings, usedSlugs);
      if (article) articles.push(article);
    }
    if (!articles.length) return [];

    return [{
      slug: date,
      date,
      title: titleMatch ? titleMatch[1].trim() : formatArchiveDate(date),
      theme,
      number: 0,
      articles,
      quiz,
      quizTitle,
    }];
  });

  issues.sort((a, b) => a.date.localeCompare(b.date));
  issues.forEach((issue, i) => { issue.number = i + 1; });
  issues.reverse();

  issuesCache = issues;
  return issues;
}

export function getArticles(): Article[] {
  return getIssues().flatMap((issue) => issue.articles);
}

export function getArticlesByCategory(key: string): Article[] {
  return getArticles().filter((a) => a.category.key === key);
}

export function getUsedCategories(): Category[] {
  const used = new Set(getArticles().map((a) => a.category.key));
  return CATEGORY_LIST.filter((c) => used.has(c.key));
}

function isoWeek(dateString: string): { year: number; week: number } {
  const [y, m, d] = dateString.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  const day = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
  const week = Math.ceil(((date.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
  return { year: date.getUTCFullYear(), week };
}

export function getWeeks(): Week[] {
  const byWeek = new Map<string, Week>();
  for (const issue of getIssues()) {
    const { year, week } = isoWeek(issue.date);
    const slug = `${year}-W${String(week).padStart(2, "0")}`;
    const entry = byWeek.get(slug) ?? { slug, label: `Settimana ${week} · ${year}`, theme: issue.theme, issues: [] };
    entry.issues.push(issue);
    byWeek.set(slug, entry);
  }
  return [...byWeek.values()].sort((a, b) => b.slug.localeCompare(a.slug));
}

export function getHistoryMeta(): HistoryState {
  const filePath = path.join(projectRoot, "history.json");
  const raw = readTextSafe(filePath);

  if (!raw) {
    return { _last_sent: "", _offset: 0, log: [] };
  }

  try {
    return JSON.parse(raw) as HistoryState;
  } catch {
    return { _last_sent: "", _offset: 0, log: [] };
  }
}

export function formatArchiveDate(dateString: string, options: Intl.DateTimeFormatOptions = {}): string {
  const dateParts = dateString.split("-").map(Number);
  if (dateParts.length !== 3 || dateParts.some(Number.isNaN)) return dateString;

  const [year, month, day] = dateParts;
  const date = new Date(Date.UTC(year, month - 1, day));
  const formatter = new Intl.DateTimeFormat("it-IT", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
    ...options,
  });

  return formatter.format(date);
}

export function formatLongDate(dateString: string): string {
  return formatArchiveDate(dateString, { weekday: "long" });
}
