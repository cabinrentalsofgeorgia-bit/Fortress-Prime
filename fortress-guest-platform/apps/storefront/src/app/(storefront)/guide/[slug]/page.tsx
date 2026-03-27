import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import {
  buildCategoryPath,
  buildGuidePath,
  fetchAllGuideStaticParams,
  fetchContentArticle,
  stripHtmlToText,
} from "@/lib/content";

type PageParams = { slug: string };

export const revalidate = 300;

export async function generateStaticParams(): Promise<Array<{ slug: string }>> {
  return fetchAllGuideStaticParams();
}

export async function generateMetadata(
  { params }: { params: Promise<PageParams> | PageParams },
): Promise<Metadata> {
  const { slug } = await Promise.resolve(params);
  const article = await fetchContentArticle(slug);

  if (!article) {
    return { title: "Guide Not Found" };
  }

  const excerpt = stripHtmlToText(article.content_body_html).slice(0, 160);
  const description =
    article.category.meta_description ||
    excerpt ||
    `Read ${article.title} from Cabin Rentals of Georgia.`;

  return {
    title: article.title,
    description,
    alternates: {
      canonical: buildGuidePath(article.slug),
    },
    openGraph: {
      title: article.title,
      description,
      type: "article",
      url: buildGuidePath(article.slug),
    },
  };
}

export default async function GuidePage(
  { params }: { params: Promise<PageParams> | PageParams },
) {
  const { slug } = await Promise.resolve(params);
  const article = await fetchContentArticle(slug);

  if (!article) {
    notFound();
  }

  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-8 px-4 py-12 sm:px-6 lg:px-8">
      <div className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">
          Sovereign Guide
        </p>
        <div className="flex flex-wrap items-center gap-2 text-sm text-slate-500">
          <Link href={buildCategoryPath(article.category.slug)} className="hover:text-slate-900">
            {article.category.name}
          </Link>
          <span>/</span>
          <span>{article.author || "Fortress Prime"}</span>
          {article.published_date ? (
            <>
              <span>/</span>
              <span>
                {new Date(article.published_date).toLocaleDateString("en-US", {
                  month: "long",
                  day: "numeric",
                  year: "numeric",
                })}
              </span>
            </>
          ) : null}
        </div>
        <h1 className="text-4xl font-semibold tracking-tight text-slate-950">{article.title}</h1>
      </div>

      <article
        className="prose prose-slate max-w-none"
        dangerouslySetInnerHTML={{ __html: article.content_body_html }}
      />
    </main>
  );
}
