import type { Metadata } from "next";

import { HomepageBookingWidget } from "@/components/booking/homepage-booking-widget";
import { LegacyBodyClasses } from "@/components/booking/legacy-body-classes";
import {
  getLegacyStorefrontShell,
  LEGACY_SHELL_INLINE_CSS,
  LEGACY_STYLESHEETS,
} from "@/lib/legacy-storefront-shell";
import { getStorefrontHomeData } from "@/lib/storefront-home";

interface AvailabilityPageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export const metadata: Metadata = {
  title: "Availability | Cabin Rentals of Georgia",
  description: "Legacy storefront shell wrapping the live cabin availability surface.",
};

export default async function AvailabilityPage({
  searchParams,
}: AvailabilityPageProps) {
  await searchParams;
  const [shell, { allProperties }] = await Promise.all([
    getLegacyStorefrontShell(),
    getStorefrontHomeData(),
  ]);

  return (
    <>
      <LegacyBodyClasses />
      {LEGACY_STYLESHEETS.map((href) => (
        <link key={href} rel="stylesheet" href={href} />
      ))}
      <style dangerouslySetInnerHTML={{ __html: LEGACY_SHELL_INLINE_CSS }} />
      <div className="legacy-homepage">
        {shell ? (
          <div dangerouslySetInnerHTML={{ __html: shell.top }} />
        ) : (
          <div className="legacy-shell-fallback">
            <h1>Blue Ridge Cabin Availability</h1>
            <p>Browse live availability and pricing across the Cabin Rentals of Georgia collection.</p>
          </div>
        )}

        <div className="legacy-shell-content">
          <div className="legacy-shell-frame-card">
            <div id="search-bar">
              <div className="region region-search-bar">
                <div id="block-crog-search-cabin-search" className="block block-crog-search">
                  <h2>Search Available Cabins</h2>
                  <HomepageBookingWidget properties={allProperties} variant="legacy" />
                </div>
              </div>
            </div>
          </div>
          <p className="legacy-shell-caption">
            Search live cabin availability and pricing across the Cabin Rentals of Georgia collection.
          </p>
        </div>

        {shell ? <div dangerouslySetInnerHTML={{ __html: shell.bottom }} /> : null}
      </div>
    </>
  );
}
