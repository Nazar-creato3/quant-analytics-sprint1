import type { MetadataRoute } from "next";
import { PUBLIC_SITEMAP_PATHS, SITE_ORIGIN } from "@/lib/public-site";

export default function sitemap(): MetadataRoute.Sitemap {
  return PUBLIC_SITEMAP_PATHS.map((path) => ({ url: `${SITE_ORIGIN}${path}` }));
}
