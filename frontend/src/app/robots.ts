import type { MetadataRoute } from "next";
import { SITE_ORIGIN } from "@/lib/public-site";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: ["/site", "/methodology", "/legal", "/login", "/signup", "/apply"],
      disallow: ["/account", "/admin", "/operator", "/api"],
    },
    sitemap: `${SITE_ORIGIN}/sitemap.xml`,
    host: SITE_ORIGIN,
  };
}
