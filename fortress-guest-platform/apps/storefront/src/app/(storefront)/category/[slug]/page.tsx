import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import {
  buildCategoryPath,
  buildGuidePath,
  fetchContentCategories,
  fetchContentCategory,
} from "@/lib/content";

type PageParams = { slug: string };

export const revalidate = 300;

export async function generateStaticParams(): Promise<Array<{ slug: string }>> {
  const categories = await fetchContentCategories();
  return categories.map((category) => ({ slug: category.slug }));
}

export async function generateMetadata(
  { params }: { params: Promise<PageParams> | PageParams },
): Promise<Metadata> {
  const { slug } = await Promise.resolve(params);
  const category = await fetchContentCategory(slug);

  if (!category) {
    return { title: "Content Category Not Found" };
  }

  const title = category.meta_title || `${category.name} | Cabin Rentals of Georgia`;
  const description =
    category.meta_description ||
    category.description ||
    `Explore sovereign guides and discovery content for ${category.name}.`;

  return {
    title,
    description,
    alternates: {
      canonical: buildCategoryPath(category.slug),
    },
    openGraph: {
      title,
      description,
      type: "website",
      url: buildCategoryPath(category.slug),
    },
  };
}

export default async function ContentCategoryPage(
  { params }: { params: Promise<PageParams> | PageParams },
) {
  const { slug } = await Promise.resolve(params);
  const category = await fetchContentCategory(slug);

  if (!category) {
    notFound();
  }

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-10 px-4 py-12 sm:px-6 lg:px-8">
      <section className="space-y-4">
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">
          Sovereign Category
        </p>
        <h1 className="text-4xl font-semibold tracking-tight text-slate-950">
          {category.name}
        </h1>
        <p className="max-w-3xl text-base leading-7 text-slate-600">
          {category.description || "This category vessel is ready for the Drupal extraction pass."}
        </p>
      </section>

      <section className="grid gap-6 lg:grid-cols-[1.4fr_0.8fr]">
        <div className="space-y-4">
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-2xl font-semibold text-slate-900">Guides</h2>
            <p className="text-sm text-slate-500">
              {category.article_count} article{category.article_count === 1 ? "" : "s"}
            </p>
          </div>

          {category.articles.length > 0 ? (
            <div className="grid gap-4">
              {category.articles.map((article) => (
                <article
                  key={article.id}
                  className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm"
                >
                  <div className="space-y-3">
                    <h3 className="text-xl font-semibold text-slate-900">
                      <Link href={buildGuidePath(article.slug)} className="hover:underline">
                        {article.title}
                      </Link>
                    </h3>
                    <p className="text-sm text-slate-500">
                      {article.author || "Fortress Prime"}
                      {article.published_date
                        ? ` / ${new Date(article.published_date).toLocaleDateString("en-US", {
                            month: "long",
                            day: "numeric",
                            year: "numeric",
                          })}`
                        : ""}
                    </p>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="rounded-3xl border border-dashed border-slate-300 bg-slate-50 p-6 text-sm text-slate-600">
              No guides are assigned yet. This page will populate after the one-time Drupal import.
            </div>
          )}
        </div>

        <aside className="space-y-4">
          <h2 className="text-2xl font-semibold text-slate-900">Related Cabins</h2>
          {category.related_cabins.length > 0 ? (
            <div className="grid gap-4">
              {category.related_cabins.map((cabin) => (
                <Link
                  key={cabin.id}
                  href={`/cabins/${cabin.slug}`}
                  className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-slate-300"
                >
                  <p className="text-lg font-semibold text-slate-900">{cabin.name}</p>
                  <p className="mt-1 text-sm text-slate-500">
                    {cabin.property_type} · Sleeps {cabin.max_guests}
                  </p>
                </Link>
              ))}
            </div>
          ) : (
            <div className="rounded-3xl border border-dashed border-slate-300 bg-slate-50 p-6 text-sm text-slate-600">
              No cabins are mapped to this category yet. The route stays live and will degrade
              cleanly until the import assigns them.
            </div>
          )}
        </aside>
      </section>
    </main>
  );
}
