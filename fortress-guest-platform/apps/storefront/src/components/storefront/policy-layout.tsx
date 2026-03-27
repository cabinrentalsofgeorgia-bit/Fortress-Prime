import Link from "next/link";

import type { PolicyPage } from "@/lib/policy-pages";

const POLICY_RICH_TEXT_CSS = `
  .policy-richtext {
    color: #334155;
  }

  .policy-richtext > * + * {
    margin-top: 1rem;
  }

  .policy-richtext p,
  .policy-richtext li,
  .policy-richtext td,
  .policy-richtext th {
    font-size: 1rem;
    line-height: 1.75;
  }

  .policy-richtext a {
    color: #0f766e;
    text-decoration: underline;
    text-underline-offset: 3px;
  }

  .policy-richtext strong,
  .policy-richtext b {
    color: #0f172a;
    font-weight: 600;
  }

  .policy-richtext em {
    color: #475569;
  }

  .policy-richtext ul,
  .policy-richtext ol {
    margin-left: 1.25rem;
    padding-left: 0.5rem;
  }

  .policy-richtext table {
    width: 100%;
    border-collapse: collapse;
    overflow: hidden;
    border-radius: 1rem;
    border: 1px solid #dbe4ea;
    background: #ffffff;
  }

  .policy-richtext th,
  .policy-richtext td {
    padding: 0.85rem 1rem;
    border: 1px solid #dbe4ea;
    vertical-align: top;
    text-align: left;
  }

  .policy-richtext tr:first-child td,
  .policy-richtext th {
    background: #f8fafc;
    color: #0f172a;
    font-weight: 600;
  }
`;

export function PolicyLayout({ page }: { page: PolicyPage }) {
  const isFaq = page.kind === "faq";

  return (
    <main className="bg-white text-slate-950">
      <style dangerouslySetInnerHTML={{ __html: POLICY_RICH_TEXT_CSS }} />
      <div className="border-b border-slate-200 bg-gradient-to-b from-slate-50 via-white to-white">
        <div className="mx-auto flex max-w-6xl flex-col gap-8 px-4 py-14 sm:px-6 lg:px-8">
          <div className="space-y-4">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-teal-700">
              {isFaq ? "Sovereign Guest FAQ" : "Sovereign Policy Mirror"}
            </p>
            <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
              <div className="max-w-3xl space-y-4">
                <h1 className="text-4xl font-semibold tracking-tight text-slate-950 sm:text-5xl">
                  {page.title}
                </h1>
                {page.introHtml ? (
                  <div
                    className="policy-richtext max-w-3xl"
                    dangerouslySetInnerHTML={{ __html: page.introHtml }}
                  />
                ) : null}
              </div>
              <div className="rounded-3xl border border-slate-200 bg-white/90 p-5 shadow-sm">
                <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">
                  Operational Status
                </p>
                <p className="mt-2 text-lg font-semibold text-slate-950">Sovereign route active</p>
                <p className="mt-1 text-sm text-slate-600">
                  Legacy Drupal content is now rendered from the Next.js storefront.
                </p>
                {page.lastUpdatedLabel ? (
                  <p className="mt-3 text-sm text-slate-500">Legacy content updated {page.lastUpdatedLabel}</p>
                ) : null}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap gap-3">
            {page.sections.map((section) => (
              <a
                key={section.id}
                href={`#${section.id}`}
                className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-teal-600 hover:text-teal-700"
              >
                {section.title}
              </a>
            ))}
          </div>
        </div>
      </div>

      <div className="mx-auto flex max-w-6xl flex-col gap-10 px-4 py-12 sm:px-6 lg:px-8">
        {isFaq
          ? page.sections.map((section) => (
              <section key={section.id} id={section.id} className="scroll-mt-24 space-y-6">
                <div className="flex items-center justify-between gap-4 border-b border-slate-200 pb-4">
                  <h2 className="text-2xl font-semibold tracking-tight text-slate-950">{section.title}</h2>
                  <span className="text-sm text-slate-500">{section.items.length} answers</span>
                </div>
                <div className="grid gap-4 lg:grid-cols-2">
                  {section.items.map((item) => (
                    <article
                      key={item.id}
                      className="rounded-3xl border border-slate-200 bg-slate-50/80 p-6 shadow-sm"
                    >
                      <h3 className="text-lg font-semibold text-slate-950">{item.question}</h3>
                      <div
                        className="policy-richtext mt-4"
                        dangerouslySetInnerHTML={{ __html: item.answerHtml }}
                      />
                    </article>
                  ))}
                </div>
              </section>
            ))
          : page.sections.map((section) => (
              <section
                key={section.id}
                id={section.id}
                className="scroll-mt-24 rounded-3xl border border-slate-200 bg-slate-50/80 p-6 shadow-sm sm:p-8"
              >
                <h2 className="text-2xl font-semibold tracking-tight text-slate-950">{section.title}</h2>
                <div
                  className="policy-richtext mt-5"
                  dangerouslySetInnerHTML={{ __html: section.html }}
                />
              </section>
            ))}

        <section className="rounded-3xl border border-teal-200 bg-teal-50/70 p-6 sm:p-8">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-teal-700">Guest Services</p>
          <h2 className="mt-3 text-2xl font-semibold tracking-tight text-slate-950">
            Need a reservation specialist?
          </h2>
          <p className="mt-2 max-w-3xl text-base leading-7 text-slate-700">
            For policy clarifications, booking changes, or arrival support, contact Cabin Rentals of Georgia
            directly or move straight into the live booking flow.
          </p>
          <div className="mt-5 flex flex-wrap gap-3">
            <a
              href={page.contact.phoneHref}
              className="rounded-full bg-slate-950 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-800"
            >
              Call {page.contact.phone}
            </a>
            <a
              href={`mailto:${page.contact.email}`}
              className="rounded-full border border-slate-300 bg-white px-5 py-3 text-sm font-semibold text-slate-900 transition hover:border-slate-950"
            >
              Email {page.contact.email}
            </a>
            <Link
              href="/book"
              className="rounded-full border border-teal-600 px-5 py-3 text-sm font-semibold text-teal-700 transition hover:bg-teal-600 hover:text-white"
            >
              Start booking
            </Link>
          </div>
        </section>
      </div>
    </main>
  );
}
