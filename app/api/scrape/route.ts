import { load } from "cheerio";

export const runtime = "nodejs";
export const maxDuration = 60;
const SAFE_MAX_PAGES = 5;
const SAFE_MAX_LISTINGS = 120;

type Listing = {
  url: string;
  price: number | null;
  price_per_m2: number | null;
  address: string;
  area_m2: number | null;
  author_name: string;
  author_company: string;
};

type RequestPayload = {
  startUrl?: string;
  pages?: number;
  limit?: number;
  delayMin?: number;
  delayMax?: number;
};

const USER_AGENTS = [
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15"
];

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function randomInt(min: number, max: number): number {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function randomDelayMs(minSeconds: number, maxSeconds: number): number {
  const min = Math.max(0, Math.floor(minSeconds * 1000));
  const max = Math.max(min, Math.floor(maxSeconds * 1000));
  return randomInt(min, max);
}

function parsePrice(raw: string): number | null {
  const chunks = raw.match(/\d[\d\s.,]*/g);
  if (!chunks || chunks.length === 0) {
    return null;
  }
  const normalized = chunks[0].replace(/[^\d]/g, "");
  return normalized ? Number(normalized) : null;
}

function parsePricePerM2(raw: string): number | null {
  const match = raw.match(/(\d[\d\s.,]*)\s*〒?\s*за\s*м²/i);
  if (!match?.[1]) {
    return null;
  }
  const normalized = match[1].replace(/[^\d]/g, "");
  return normalized ? Number(normalized) : null;
}

function parseArea(raw: string): number | null {
  const match = raw.match(/(\d+[.,]?\d*)\s*м²/i) ?? raw.match(/(\d+[.,]?\d*)/);
  if (!match) {
    return null;
  }
  return Number(match[1].replace(",", "."));
}

function normalizeCompany(raw: string): string {
  const value = raw.trim();
  if (!value) {
    return "";
  }
  if (/^[\d:\-+T.Z\s]+$/.test(value)) {
    return "None";
  }
  if (!/[A-Za-zА-Яа-яЁё]/.test(value)) {
    return "None";
  }
  return value;
}

function csvEscape(value: string | number | null): string {
  if (value === null || value === undefined) {
    return "";
  }
  const raw = String(value);
  if (raw.includes(";") || raw.includes('"') || raw.includes("\n")) {
    return `"${raw.replace(/"/g, '""')}"`;
  }
  return raw;
}

function extractByLabel($: ReturnType<typeof load>, label: string): string {
  const labelLower = label.toLowerCase();
  let result = "";

  $("dl").each((_, dl) => {
    if (result) {
      return;
    }
    const term = $(dl).find("dt").first().text().trim().toLowerCase();
    const value = $(dl).find("dd").first().text().trim();
    if (term.includes(labelLower) && value) {
      result = value;
    }
  });

  return result;
}

function extractAddressFromPageTitle(pageTitle: string): string {
  const match = pageTitle.match(/:\s*(.*?)\s+—\s+за\s+\d/i);
  return match?.[1]?.trim() ?? "";
}

function extractAddressFromH1(h1: string): string {
  if (h1.includes("·")) {
    return "";
  }
  const parts = h1.split(",");
  if (parts.length < 2) {
    return "";
  }
  return parts.slice(1).join(",").trim();
}

function parseNextPageUrl(html: string, currentUrl: string): string | null {
  const $ = load(html);
  const nextHref = $("a[rel='next']").first().attr("href");
  if (!nextHref) {
    return null;
  }
  return new URL(nextHref, currentUrl).toString();
}

function extractListingLinks(html: string, baseUrl: string): string[] {
  const $ = load(html);
  const links = new Set<string>();
  $("a[href*='/a/show/']").each((_, a) => {
    const href = $(a).attr("href");
    if (href) {
      links.add(new URL(href, baseUrl).toString());
    }
  });
  return [...links];
}

async function fetchHtml(url: string): Promise<string> {
  const response = await fetch(url, {
    headers: {
      "User-Agent": USER_AGENTS[randomInt(0, USER_AGENTS.length - 1)],
      "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
    },
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} for ${url}`);
  }
  return response.text();
}

function parseDetail(url: string, html: string): Listing {
  const $ = load(html);
  const pageText = $.text();
  const pageTitle = $("title").first().text().trim();
  const h1 = $("h1").first().text().trim();

  const priceText = $(".offer__price").first().text().trim();
  const price = parsePrice(priceText);
  const pricePerM2 = parsePricePerM2(priceText);

  let address = $(".offer__location-title").first().text().trim();
  if (!address && h1) {
    address = extractAddressFromH1(h1);
  }
  if (!address && pageTitle) {
    address = extractAddressFromPageTitle(pageTitle);
  }

  const areaRaw = extractByLabel($, "Площадь");
  const areaFromH1 = parseArea(h1);
  const area = parseArea(areaRaw) ?? areaFromH1;

  let authorName = $(".owners__name").first().text().trim();
  if (!authorName) {
    authorName = $("[data-name='owner-name']").first().text().trim();
  }

  let authorCompany = $(".owners__company").first().text().trim();
  if (!authorCompany) {
    const m = pageText.match(/Работает в компании\s+([^\n]+)/);
    if (m?.[1]) {
      authorCompany = m[1].trim();
    } else if (pageText.includes("Крыша Агент")) {
      authorCompany = "Крыша Агент";
    } else if (pageText.includes("Специалист")) {
      authorCompany = "Специалист";
    }
  }

  return {
    url,
    price,
    price_per_m2: pricePerM2,
    address,
    area_m2: area,
    author_name: authorName,
    author_company: normalizeCompany(authorCompany)
  };
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as RequestPayload;
    const startUrl = (body.startUrl ?? "").trim();
    const requestedPages = Number(body.pages ?? 2);
    const requestedLimit = Number(body.limit ?? 30);
    const pages = Math.max(1, Math.min(requestedPages, SAFE_MAX_PAGES));
    const limitRaw =
      requestedLimit === 0
        ? SAFE_MAX_LISTINGS
        : Math.max(1, Math.min(requestedLimit, SAFE_MAX_LISTINGS));
    const limit = limitRaw;
    const delayMin = Math.max(0, Number(body.delayMin ?? 1));
    const delayMax = Math.max(delayMin, Number(body.delayMax ?? 2.5));

    if (!startUrl.startsWith("http")) {
      return Response.json(
        { error: "Укажите корректный startUrl (http/https)." },
        { status: 400 }
      );
    }

    if (requestedPages > SAFE_MAX_PAGES) {
      return Response.json(
        {
          error: `Слишком много страниц для веб-версии Vercel. Максимум: ${SAFE_MAX_PAGES}.`
        },
        { status: 400 }
      );
    }

    if (requestedLimit === 0) {
      return Response.json(
        {
          error:
            `Параметр limit=0 (без лимита) в веб-версии может вызвать таймаут. ` +
            `Укажите лимит до ${SAFE_MAX_LISTINGS}.`
        },
        { status: 400 }
      );
    }

    if (requestedLimit > SAFE_MAX_LISTINGS) {
      return Response.json(
        {
          error: `Слишком большой лимит объявлений. Максимум: ${SAFE_MAX_LISTINGS}.`
        },
        { status: 400 }
      );
    }

    let currentUrl: string | null = startUrl;
    let pageNum = 0;
    const seen = new Set<string>();
    const listings: Listing[] = [];

    while (currentUrl && pageNum < pages && listings.length < limit) {
      pageNum += 1;
      const html = await fetchHtml(currentUrl);
      const links = extractListingLinks(html, currentUrl);

      for (const link of links) {
        if (seen.has(link)) {
          continue;
        }
        seen.add(link);
        try {
          const detailHtml = await fetchHtml(link);
          listings.push(parseDetail(link, detailHtml));
          if (listings.length >= limit) {
            break;
          }
          await sleep(randomDelayMs(delayMin, delayMax));
        } catch {
          // Skip broken ad and continue.
        }
      }

      currentUrl = parseNextPageUrl(html, currentUrl);
      await sleep(randomDelayMs(delayMin, delayMax));
    }

    const header = [
      "url",
      "price",
      "price_per_m2",
      "address",
      "area_m2",
      "author_name",
      "author_company"
    ];
    const rows = listings.map((item) =>
      [
        csvEscape(item.url),
        csvEscape(item.price),
        csvEscape(item.price_per_m2),
        csvEscape(item.address),
        csvEscape(item.area_m2),
        csvEscape(item.author_name),
        csvEscape(item.author_company)
      ].join(";")
    );

    const csv = `\uFEFF${header.join(";")}\n${rows.join("\n")}`;
    return new Response(csv, {
      status: 200,
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": 'attachment; filename="krisha_export.csv"'
      }
    });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Не удалось выполнить парсинг.";
    return Response.json({ error: message }, { status: 500 });
  }
}
