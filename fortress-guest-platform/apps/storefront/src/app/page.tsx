import type { Metadata } from "next";

import StorefrontHomePage from "./(storefront)/page";
import { StorefrontSurface } from "@/components/storefront/storefront-surface";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "North Georgia Cabin Rentals in Blue Ridge, GA | Blue Ridge Luxury Cabins",
  description:
    "North Georgia Cabin Rentals near Blue Ridge, GA - Cabin Rentals of Georgia offers luxurious vacation cabin rentals with hot tubs, mountain views, river views, and lake views.",
  alternates: {
    canonical: "/",
  },
  openGraph: {
    title: "North Georgia Cabin Rentals in Blue Ridge, GA | Blue Ridge Luxury Cabins",
    description:
      "Luxury North Georgia cabin rentals near Blue Ridge, GA with mountain, river, and lake experiences.",
    type: "website",
    url: "/",
    siteName: "Cabin Rentals of Georgia",
    images: [
      {
        url: "https://www.cabin-rentals-of-georgia.com/sites/default/files/CROG_FBimage.jpg",
      },
    ],
  },
};

export default function HomePage() {
  return (
    <StorefrontSurface>
      <StorefrontHomePage />
    </StorefrontSurface>
  );
}
