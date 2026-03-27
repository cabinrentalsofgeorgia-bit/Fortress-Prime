import type { MetadataRoute } from "next";

export default async function robots(): Promise<MetadataRoute.Robots> {
  const appUrl = (
    process.env.NEXT_PUBLIC_COMMAND_CENTER_URL ||
    process.env.NEXT_PUBLIC_APP_URL ||
    "https://crog-ai.com"
  ).replace(/\/$/, "");
  return {
    rules: [
      {
        userAgent: "*",
        disallow: "/",
      },
    ],
    host: appUrl,
  };
}
