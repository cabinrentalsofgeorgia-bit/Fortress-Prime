export interface NavItem {
  label: string;
  href: string;
  description?: string;
  external?: boolean;
}

export interface NavGroup {
  label: string;
  href: string;
  items: NavItem[];
}

export interface FooterColumn {
  title: string;
  items: NavItem[];
}

export interface HeroPayload {
  headline: string;
  subheadline: string;
  ctaText: string;
  ctaTarget: string;
  backgroundImageUrl: string;
}

export interface StorefrontContactPayload {
  businessName: string;
  phoneLabel: string;
  phoneHref: string;
  addressLines: string[];
}

export const STOREFRONT_NAV_GROUPS: NavGroup[] = [
  {
    label: "Blue Ridge Cabins",
    href: "/blue-ridge-cabins?all=1",
    items: [
      {
        label: "Blue Ridge Luxury Cabins",
        href: "/cabins/all/blue-ridge-luxury",
      },
      {
        label: "Family Reunion Cabins",
        href: "/cabins/all/family-reunion",
      },
      {
        label: "Corporate Retreat Cabins",
        href: "/cabins/all/corporate-retreats",
      },
      {
        label: "Pet Friendly Cabins",
        href: "/cabins/amenities/pet-friendly",
      },
      {
        label: "Mountain View Cabins",
        href: "/cabins/all/mountain-view",
      },
      {
        label: "Creek + Riverfront Cabins",
        href: "/cabins/all/river-front",
      },
      {
        label: "Lake View Cabins",
        href: "/cabins/all/lake-view",
      },
      {
        label: "All Cabin Rentals",
        href: "/blue-ridge-cabins?all=1",
      },
    ],
  },
  {
    label: "Blue Ridge Experience",
    href: "/blue-ridge-experience?all=1",
    items: [
      {
        label: "About Blue Ridge, GA",
        href: "/about-blue-ridge-ga",
      },
      {
        label: "Blue Ridge, GA Activities",
        href: "/blue-ridge-georgia-activities",
      },
    ],
  },
  {
    label: "Blue Ridge Memories",
    href: "/blue-ridge-memories?all=1",
    items: [
      {
        label: "Guest Reviews",
        href: "/blue-ridge-memories?all=1",
      },
      {
        label: "Property Management",
        href: "/blue-ridge-property-management",
      },
      {
        label: "About Us",
        href: "/about-us",
      },
    ],
  },
];

export const STOREFRONT_UTILITY_LINKS: NavItem[] = [
  { label: "FAQ", href: "/faq" },
  { label: "Blog", href: "/blogs" },
  { label: "Policies", href: "/rental-policies" },
  { label: "About Us", href: "/about-us" },
  { label: "Property Management", href: "/blue-ridge-property-management" },
];

export const STOREFRONT_HOME_HERO: HeroPayload = {
  headline: "Luxury Cabins in Blue Ridge, GA",
  subheadline:
    "Family-owned for over 20 years, Cabin Rentals of Georgia pairs world-class hospitality with hand-picked mountain, river, and lake retreats just north of Atlanta.",
  ctaText: "Search Availability",
  ctaTarget: "/availability",
  backgroundImageUrl:
    "https://media.cabin-rentals-of-georgia.com/sites/default/files/slide_rustic.jpg",
};

export const STOREFRONT_CONTACT: StorefrontContactPayload = {
  businessName: "Cabin Rentals of Georgia, L.L.C.",
  phoneLabel: "706-432-2140",
  phoneHref: "tel:+17064322140",
  addressLines: [
    "86 Huntington Way",
    "Blue Ridge, Georgia 30513",
  ],
};

export const STOREFRONT_SOCIAL_LINKS: NavItem[] = [
  {
    label: "Facebook",
    href: "https://www.facebook.com/CabinRentalsofGeorgia",
    external: true,
  },
  {
    label: "Instagram",
    href: "https://www.instagram.com/crgluxury/",
    external: true,
  },
  {
    label: "Twitter",
    href: "https://x.com/CRGLuxury",
    external: true,
  },
  {
    label: "Pinterest",
    href: "https://pinterest.com/crgluxury/",
    external: true,
  },
  {
    label: "YouTube",
    href: "https://www.youtube.com/channel/UCi4BOs7O9xcsAUIMpG0OKlg",
    external: true,
  },
];

export const STOREFRONT_FOOTER_COLUMNS: FooterColumn[] = [
  {
    title: "North Georgia Cabins",
    items: [
      { label: "2 Bedroom Cabins", href: "/cabins/2-bedroom/all" },
      { label: "3 Bedroom Cabins", href: "/cabins/3-bedroom/all" },
      { label: "4 Bedroom Cabins", href: "/cabins/4-bedroom/all" },
      { label: "5 Bedroom Cabins", href: "/cabins/5-bedroom/all" },
      { label: "7 Bedroom Cabins", href: "/cabins/7-bedroom/all" },
    ],
  },
  {
    title: "Popular Collections",
    items: [
      { label: "Blue Ridge Luxury Cabins", href: "/cabins/all/blue-ridge-luxury" },
      { label: "Family Reunion Cabins", href: "/cabins/all/family-reunion" },
      { label: "Mountain View Cabins", href: "/cabins/all/mountain-view" },
      { label: "River Front Cabins", href: "/cabins/all/river-front" },
      { label: "Lake View Cabins", href: "/cabins/all/lake-view" },
    ],
  },
  {
    title: "Company",
    items: [
      { label: "About Us", href: "/about-us" },
      { label: "FAQ", href: "/faq" },
      { label: "Blog", href: "/blogs" },
      { label: "Property Management", href: "/blue-ridge-property-management" },
      { label: "Privacy Policy", href: "/node/1213" },
    ],
  },
];
