import { cache } from "react";
import { readFile } from "node:fs/promises";
import path from "node:path";

const LEGACY_HOME_ARCHIVE_PATH = path.join(
  process.cwd(),
  "src",
  "data",
  "legacy",
  "legacy-home-20180820.html",
);

export const LEGACY_STYLESHEETS = [
  "https://media.cabin-rentals-of-georgia.com/sites/default/files/cdn/css/https/css_SKbNMOc1i5AgeZ7-cTHjzd_9Cg0RY0536AT-kgTpB-E.css",
  "https://media.cabin-rentals-of-georgia.com/sites/default/files/cdn/css/https/css_0fz1wBlEB9ZXyBREh7u4XQ6rea-EKJU0SytQbc2V5Hc.css",
  "https://media.cabin-rentals-of-georgia.com/sites/default/files/cdn/css/https/css_gQ0JO_61q2psf131VH82FDSRbMEScWuP6ORs03PXM28.css",
  "https://media.cabin-rentals-of-georgia.com/sites/default/files/cdn/css/https/css_1dU5sBnAxS8sKrmmLQdajCtp1yCGAoHlvml8NeJiF6M.css",
  "https://media.cabin-rentals-of-georgia.com/sites/default/files/cdn/css/https/css_nfA0D9mYU1cnQ3JzmZgExcT_hMC9QnDn92TpgT2EWng.css",
] as const;

export const LEGACY_SHELL_INLINE_CSS = `
body.front {
  background: #ffffff !important;
  color: #533e27 !important;
}

.legacy-homepage img {
  max-width: 100%;
  height: auto;
}

.legacy-homepage #banner-wrapper {
  width: 100% !important;
  max-width: 1340px;
  height: auto !important;
}

.legacy-homepage #banner {
  position: relative;
  width: 100% !important;
  min-height: 466px;
  overflow: hidden;
}

.legacy-homepage #banner ul {
  margin: 0;
  padding: 0;
  list-style: none;
}

.legacy-homepage #banner ul li {
  display: none;
}

.legacy-homepage #banner ul li:first-child {
  display: block;
}

.legacy-homepage #banner ul li img {
  display: block;
  width: 100%;
}

.legacy-homepage .legacy-booking-widget {
  min-height: 128px;
}

.legacy-homepage .legacy-booking-widget #select-cabin-name,
.legacy-homepage .legacy-booking-widget #arrival-date-popup,
.legacy-homepage .legacy-booking-widget #departure-date-popup,
.legacy-homepage .legacy-booking-widget #guest-count-popup {
  float: left;
}

.legacy-homepage .legacy-booking-widget #guest-count-popup {
  margin-left: 8px;
  width: 92px;
}

.legacy-homepage .legacy-booking-widget #guest-count-popup .form-text {
  width: 88px;
}

.legacy-homepage .legacy-booking-widget .legacy-search-meta,
.legacy-homepage .legacy-booking-widget .legacy-search-feedback {
  clear: both;
}

.legacy-homepage .legacy-booking-widget .legacy-search-meta {
  padding-top: 12px;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.legacy-homepage .legacy-booking-widget .legacy-search-feedback {
  margin-top: 12px;
  padding: 10px 14px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.86);
  font-size: 13px;
  line-height: 1.5;
}

.legacy-homepage .legacy-booking-widget .legacy-search-feedback span,
.legacy-homepage .legacy-booking-widget .legacy-search-feedback a {
  display: block;
}

.legacy-homepage .legacy-booking-widget .legacy-search-feedback a {
  margin-top: 6px;
  font-weight: bold;
}

.legacy-homepage .legacy-booking-widget .legacy-search-feedback-error {
  border: 1px solid #b76b5d;
  color: #7b2310;
}

.legacy-homepage .legacy-booking-widget .legacy-search-feedback-success {
  border: 1px solid #a7b479;
  color: #4f5b1c;
}

.legacy-homepage-fallback,
.legacy-shell-fallback {
  margin: 0 auto;
  max-width: 1200px;
  padding: 48px 24px 64px;
}

.legacy-homepage-fallback h1,
.legacy-shell-fallback h1 {
  margin: 0 0 12px;
  color: #533e27;
  font-size: 40px;
  line-height: 1.1;
}

.legacy-homepage-fallback p,
.legacy-shell-fallback p {
  margin: 0 0 24px;
  color: #6b5845;
  font-size: 18px;
  line-height: 1.7;
}

.legacy-shell-content {
  margin: 0 auto;
  max-width: 1340px;
  padding: 24px 20px 48px;
}

.legacy-shell-frame-card {
  overflow: hidden;
  border: 1px solid #d7c7b5;
  border-radius: 18px;
  background: #ffffff;
  box-shadow: 0 20px 40px rgba(83, 62, 39, 0.08);
}

.legacy-shell-frame {
  display: block;
  width: 100%;
  min-height: 1200px;
  border: 0;
  background: #ffffff;
}

.legacy-shell-caption {
  padding: 16px 20px 0;
  color: #6b5845;
  font-size: 14px;
  line-height: 1.6;
}

@media all and (max-width: 980px) {
  .legacy-homepage #banner {
    min-height: 0;
  }

  .legacy-homepage .legacy-booking-widget #select-cabin-name,
  .legacy-homepage .legacy-booking-widget #arrival-date-popup,
  .legacy-homepage .legacy-booking-widget #departure-date-popup,
  .legacy-homepage .legacy-booking-widget #guest-count-popup {
    float: none;
    margin-left: 0;
    width: 100%;
  }

  .legacy-homepage .legacy-booking-widget #guest-count-popup .form-text {
    width: 100%;
  }

  .legacy-shell-content {
    padding-inline: 14px;
  }

  .legacy-shell-frame {
    min-height: 900px;
  }
}
`;

function stripScripts(html: string): string {
  return html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "");
}

function absolutizeLegacyAssets(html: string): string {
  return html
    .replace(/(src|href)="\/sites\//g, '$1="https://www.cabin-rentals-of-georgia.com/sites/')
    .replace(/url\(\/sites\//g, "url(https://www.cabin-rentals-of-georgia.com/sites/");
}

export const getLegacyStorefrontShell = cache(async () => {
  try {
    const html = await readFile(LEGACY_HOME_ARCHIVE_PATH, "utf-8");
    const start = html.indexOf('<div id="nav-bar">');
    const searchStart = html.indexOf('<div id="search-bar">');
    const searchEndMarker = '</div></div><div class="clearfix"></div><div id="page-wrapper">';
    const searchEnd = html.indexOf(searchEndMarker, searchStart);
    const footerEnd = html.indexOf('<form id="back-button-check-form">');

    if (start === -1 || searchStart === -1 || searchEnd === -1 || footerEnd === -1) {
      return null;
    }

    const pageWrapperStart = searchEnd + '</div></div><div class="clearfix"></div>'.length;

    return {
      top: absolutizeLegacyAssets(html.slice(start, searchStart)),
      bottom: absolutizeLegacyAssets(stripScripts(html.slice(pageWrapperStart, footerEnd))),
    };
  } catch {
    return null;
  }
});
