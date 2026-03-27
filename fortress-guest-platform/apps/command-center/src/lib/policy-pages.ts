import { cache } from "react";
import { readFile } from "node:fs/promises";
import path from "node:path";

export type PolicySlug = "privacy-policy" | "terms-and-conditions" | "faq";

type LegacyPolicyArchive = {
  title: string;
  original_slug: string;
  content_body: string;
  legacy_updated_at?: number;
  signed_at?: string;
};

export type PolicySection = {
  id: string;
  title: string;
  html: string;
};

export type FaqItem = {
  id: string;
  question: string;
  answerHtml: string;
};

export type FaqSection = {
  id: string;
  title: string;
  items: FaqItem[];
};

type PolicyContact = {
  email: string;
  phone: string;
  phoneHref: string;
};

type BasePolicyPage = {
  slug: PolicySlug;
  title: string;
  introHtml: string | null;
  lastUpdatedLabel: string | null;
  description: string;
  contact: PolicyContact;
};

export type DocumentPolicyPage = BasePolicyPage & {
  kind: "document";
  sections: PolicySection[];
};

export type FaqPolicyPage = BasePolicyPage & {
  kind: "faq";
  sections: FaqSection[];
};

export type PolicyPage = DocumentPolicyPage | FaqPolicyPage;

const POLICY_ARCHIVE_FILES: Record<PolicySlug, string> = {
  "privacy-policy": "%2Fprivacy-policy.json",
  "terms-and-conditions": "%2Fterms-and-conditions.json",
  faq: "faq.json",
};

const POLICY_DESCRIPTIONS: Record<PolicySlug, string> = {
  "privacy-policy":
    "Read the Cabin Rentals of Georgia privacy policy covering information handling, cookies, security, and marketing opt-out requests.",
  "terms-and-conditions":
    "Review the Cabin Rentals of Georgia SMS terms and conditions for promotional and reservation-related messages.",
  faq:
    "Browse the Cabin Rentals of Georgia guest FAQ covering booking, cabin policies, amenities, travel details, and Blue Ridge local information.",
};

const DEFAULT_CONTACT: PolicyContact = {
  email: "info@cabin-rentals-of-georgia.com",
  phone: "(706) 432-2140",
  phoneHref: "tel:+17064322140",
};

const POLICY_DATA_DIR = path.join(process.cwd(), "src", "data", "legacy", "testimonials");

export const getPolicyPage = cache(async (slug: PolicySlug): Promise<PolicyPage | null> => {
  const archive = await readPolicyArchive(slug);

  if (!archive) {
    return null;
  }

  const basePage = {
    slug,
    title: archive.title,
    description: POLICY_DESCRIPTIONS[slug],
    lastUpdatedLabel: formatUpdatedLabel(archive),
    contact: DEFAULT_CONTACT,
  };

  if (slug === "faq") {
    const parsed = splitByHeading(archive.content_body, "h2");
    return {
      ...basePage,
      kind: "faq",
      introHtml: parsed.introHtml,
      sections: parsed.sections.map((section) => ({
        id: slugify(section.title),
        title: section.title,
        items: splitByHeading(section.html, "h4").sections.map((item) => ({
          id: slugify(item.title),
          question: item.title,
          answerHtml: item.html,
        })),
      })),
    };
  }

  const parsed = splitByHeading(archive.content_body, "h2");
  return {
    ...basePage,
    kind: "document",
    introHtml: parsed.introHtml,
    sections: parsed.sections.map((section) => ({
      id: slugify(section.title),
      title: section.title,
      html: section.html,
    })),
  };
});

async function readPolicyArchive(slug: PolicySlug): Promise<LegacyPolicyArchive | null> {
  const fileName = POLICY_ARCHIVE_FILES[slug];

  try {
    const raw = await readFile(path.join(POLICY_DATA_DIR, fileName), "utf-8");
    return JSON.parse(raw) as LegacyPolicyArchive;
  } catch {
    return null;
  }
}

function splitByHeading(
  html: string,
  headingTag: "h2" | "h4",
): { introHtml: string | null; sections: Array<{ title: string; html: string }> } {
  const matcher = new RegExp(`<${headingTag}\\b[^>]*>([\\s\\S]*?)<\\/${headingTag}>`, "gi");
  const sections: Array<{ title: string; html: string }> = [];
  let introHtml = "";
  let currentTitle: string | null = null;
  let cursor = 0;

  for (const match of html.matchAll(matcher)) {
    const blockStart = match.index ?? 0;
    const fragment = normalizeHtmlFragment(html.slice(cursor, blockStart));

    if (currentTitle) {
      if (fragment) {
        sections.push({ title: currentTitle, html: fragment });
      }
    } else if (fragment) {
      introHtml = fragment;
    }

    currentTitle = stripHtml(match[1] ?? "");
    cursor = blockStart + match[0].length;
  }

  const tail = normalizeHtmlFragment(html.slice(cursor));
  if (currentTitle) {
    if (tail) {
      sections.push({ title: currentTitle, html: tail });
    }
  } else if (tail) {
    introHtml = tail;
  }

  return {
    introHtml: introHtml || null,
    sections,
  };
}

function normalizeHtmlFragment(fragment: string): string {
  return fragment
    .replace(/\r\n/g, "\n")
    .replace(/&nbsp;/g, " ")
    .replace(/<p>\s*<\/p>/gi, "")
    .trim();
}

function stripHtml(value: string): string {
  return decodeHtmlEntities(value.replace(/<[^>]+>/g, " "))
    .replace(/\s+/g, " ")
    .trim();
}

function slugify(value: string): string {
  return stripHtml(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function formatUpdatedLabel(archive: LegacyPolicyArchive): string | null {
  if (typeof archive.legacy_updated_at === "number") {
    return formatDate(new Date(archive.legacy_updated_at * 1000));
  }

  if (archive.signed_at) {
    return formatDate(new Date(archive.signed_at));
  }

  return null;
}

function formatDate(date: Date): string | null {
  if (Number.isNaN(date.getTime())) {
    return null;
  }

  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

function decodeHtmlEntities(value: string): string {
  const namedEntities: Record<string, string> = {
    "&amp;": "&",
    "&apos;": "'",
    "&ldquo;": '"',
    "&rdquo;": '"',
    "&lsquo;": "'",
    "&rsquo;": "'",
    "&mdash;": "-",
    "&ndash;": "-",
    "&hellip;": "...",
    "&nbsp;": " ",
    "&uuml;": "u",
  };

  return value
    .replace(/&#(\d+);/g, (_, code: string) => String.fromCodePoint(Number.parseInt(code, 10)))
    .replace(/&#x([0-9a-f]+);/gi, (_, code: string) => String.fromCodePoint(Number.parseInt(code, 16)))
    .replace(/&[a-z]+;/gi, (entity) => namedEntities[entity] ?? entity);
}
