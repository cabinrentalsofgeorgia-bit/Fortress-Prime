import type { Metadata } from "next";

import { ArchivePageContent, generateArchiveMetadata } from "@/lib/archive-page";
import {
  fetchMirroredNode,
  fetchMirroredNodeStaticParams,
  formatMirroredNodeLabel,
  resolveMirroredNodePathFromSlug,
  stripHtmlToText,
} from "@/lib/mirrored-nodes";

type PageParams = { slug: string[] };

const MIRRORED_NODE_RICH_TEXT_CSS = `
  .mirrored-node-richtext {
    color: #334155;
  }

  .mirrored-node-richtext > * + * {
    margin-top: 1rem;
  }

  .mirrored-node-richtext p,
  .mirrored-node-richtext li,
  .mirrored-node-richtext td,
  .mirrored-node-richtext th {
    font-size: 1rem;
    line-height: 1.8;
  }

  .mirrored-node-richtext a {
    color: #0f766e;
    text-decoration: underline;
    text-underline-offset: 3px;
  }

  .mirrored-node-richtext img,
  .mirrored-node-richtext iframe,
  .mirrored-node-richtext table {
    max-width: 100%;
  }

  .mirrored-node-richtext img {
    height: auto;
    border-radius: 1rem;
  }

  .mirrored-node-richtext ul,
  .mirrored-node-richtext ol {
    margin-left: 1.25rem;
    padding-left: 0.5rem;
  }

  .mirrored-node-richtext table {
    width: 100%;
    border-collapse: collapse;
    overflow: hidden;
    border-radius: 1rem;
    border: 1px solid #dbe4ea;
    background: #ffffff;
  }

  .mirrored-node-richtext th,
  .mirrored-node-richtext td {
    padding: 0.85rem 1rem;
    border: 1px solid #dbe4ea;
    vertical-align: top;
    text-align: left;
  }
`;

export const dynamic = "force-dynamic";
export const revalidate = 300;

export async function generateStaticParams(): Promise<Array<{ slug: string[] }>> {
  return fetchMirroredNodeStaticParams();
}

export async function generateMetadata(
  { params }: { params: Promise<PageParams> | PageParams },
): Promise<Metadata> {
  const { slug } = await Promise.resolve(params);
  const path = resolveMirroredNodePathFromSlug(slug);
  const node = await fetchMirroredNode(path);

  if (!node) {
    return generateArchiveMetadata({
      slug: slug.join("/"),
      canonicalPath: path,
    });
  }

  const description = stripHtmlToText(node.raw_html).slice(0, 160) || `Read ${node.title}.`;

  return {
    title: node.title,
    description,
    alternates: {
      canonical: node.canonical_path,
    },
    openGraph: {
      title: node.title,
      description,
      type: "article",
      url: node.canonical_path,
    },
  };
}

export default async function MirroredNodePage(
  { params }: { params: Promise<PageParams> | PageParams },
) {
  const { slug } = await Promise.resolve(params);
  const path = resolveMirroredNodePathFromSlug(slug);
  const node = await fetchMirroredNode(path);

  if (!node || !node.raw_html.trim()) {
    return ArchivePageContent({
      slug: slug.join("/"),
      canonicalPath: path,
      pathLabel: "Requested legacy path",
      pathValue: path,
    });
  }

  return (
    <main className="bg-white text-slate-950">
      <style dangerouslySetInnerHTML={{ __html: MIRRORED_NODE_RICH_TEXT_CSS }} />
      <section className="border-b border-slate-200 bg-gradient-to-b from-slate-50 via-white to-white">
        <div className="mx-auto flex max-w-5xl flex-col gap-5 px-4 py-14 sm:px-6 lg:px-8">
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-teal-700">
            {formatMirroredNodeLabel(node.content_category)}
          </p>
          <h1 className="max-w-4xl text-4xl font-semibold tracking-tight text-slate-950 sm:text-5xl">
            {node.title}
          </h1>
          <div className="flex flex-wrap items-center gap-3 text-sm text-slate-500">
            <span className="rounded-full border border-slate-200 bg-white px-4 py-2">{node.canonical_path}</span>
            <span className="rounded-full border border-slate-200 bg-white px-4 py-2">
              Updated {new Date(node.updated_at).toLocaleDateString("en-US")}
            </span>
          </div>
          {node.body_text_preview ? (
            <p className="max-w-3xl text-base leading-7 text-slate-600">{node.body_text_preview}</p>
          ) : null}
        </div>
      </section>

      <section className="mx-auto max-w-5xl px-4 py-12 sm:px-6 lg:px-8">
        <article
          className="mirrored-node-richtext"
          dangerouslySetInnerHTML={{ __html: node.raw_html }}
        />
      </section>
    </main>
  );
}
