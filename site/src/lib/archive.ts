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

export type ArchiveItem = {
  slug: string;
  filePath: string;
  title: string;
  date: string;
  year: number;
  theme: string;
  excerpt: string;
  body: string;
  html: string;
  source: string;
};

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

function stripMarkdown(input: string): string {
  return input
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1")
    .replace(/[#>*_`~>\-]/g, " ")
    .replace(/\n+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function makeUniqueSlug(baseSlug: string, used: Set<string>): string {
  let slug = baseSlug;
  let counter = 1;

  while (used.has(slug)) {
    slug = `${baseSlug}-${counter}`;
    counter += 1;
  }

  used.add(slug);
  return slug;
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

export function getArchiveEntries(): ArchiveItem[] {
  const dailyRoot = path.join(archiveRoot, "2026");
  if (!fs.existsSync(dailyRoot)) return [];

  const files = listMarkdownFiles(dailyRoot);
  const usedSlugs = new Set<string>();

  return files.flatMap((filePath) => {
    const source = readTextSafe(filePath);
    if (!source) return [];

    const baseName = path.basename(filePath, ".md");
    const titleMatch = source.match(/^#\s+(.+)$/m);
    const title = titleMatch ? titleMatch[1].trim() : baseName;

    const themeMatch = source.match(/Tema della settimana:\s+\*(.+?)\*/m);
    const theme = themeMatch ? themeMatch[1].trim() : "DailyCulture";

    const body = source.replace(/^#.*\n\n.*?Tema della settimana:.*\n\n/, "");
    const excerpt = stripMarkdown(body).slice(0, 220);

    const date = baseName;
    const year = Number(baseName.slice(0, 4));
    const slug = makeUniqueSlug(baseName, usedSlugs);

    return [{
      slug,
      filePath,
      title,
      date,
      year,
      theme,
      excerpt,
      body,
      html: marked.parse(body, { breaks: true }),
      source: filePath.replace(projectRoot + path.sep, ""),
    }];
  });
}

export function getWeeklySummaries() {
  const weeklyRoot = path.join(archiveRoot, "settimane");
  if (!fs.existsSync(weeklyRoot)) return [];

  const files = listMarkdownFiles(weeklyRoot);
  const usedSlugs = new Set<string>();

  return files.flatMap((filePath) => {
    const source = readTextSafe(filePath);
    if (!source) return [];

    const baseName = path.basename(filePath, ".md");
    const match = source.match(/^#\s+Settimana\s+(\d{4}-W\d{2})/m);
    const label = match ? match[1] : baseName;
    const excerpt = stripMarkdown(source).slice(0, 220);
    const slug = makeUniqueSlug(baseName, usedSlugs);

    return [{
      slug,
      filePath,
      label,
      excerpt,
      html: marked.parse(source, { breaks: true }),
      source: filePath.replace(projectRoot + path.sep, ""),
    }];
  });
}

export function getLatestEntries(limit = 6) {
  return getArchiveEntries()
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, limit);
}

export function formatArchiveDate(dateString: string): string {
  const dateParts = dateString.split("-").map(Number);
  if (dateParts.length !== 3 || dateParts.some(Number.isNaN)) return dateString;

  const [year, month, day] = dateParts;
  const date = new Date(Date.UTC(year, month - 1, day));
  const formatter = new Intl.DateTimeFormat("it-IT", {
    day: "2-digit",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });

  return formatter.format(date);
}
