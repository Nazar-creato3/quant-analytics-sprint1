/**
 * Next.js Edge Middleware
 * Protects all routes except /login — redirects to /login if no access token.
 * Runs on the edge before any page or API route handler.
 *
 * CRITICAL: /_next/* (CSS, JS, fonts, HMR) must NEVER hit auth — blocked CSS = unstyled page.
 */
import { NextRequest, NextResponse } from "next/server";
import {
  stripSensitiveLoginQueryParams,
  urlHasSensitiveLoginQueryParams,
} from "@/lib/login-security";
import { updateSession } from "@/lib/supabase/middleware";

const PUBLIC_PATHS = [
  "/login",
  "/signup",
  "/apply",
  "/legal",
  "/methodology",
  "/pricing",
  "/site",
  "/statement-review",
  "/support",
  "/api",
  "/_next",
  "/favicon.ico",
  "/robots.txt",
  "/sitemap.xml",
  "/logo.png",
  "/api/supabase-health",
];

/** Files served from /public must bypass auth (e.g. logo.png on /login). */
const PUBLIC_STATIC =
  /\.(?:png|jpe?g|gif|svg|ico|webp|txt|xml|json|webmanifest|woff2?|ttf|eot|css|js|map)$/i;

function isPublicPath(pathname: string): boolean {
  // Belt-and-suspenders: every Next.js internal asset bypasses auth on hard refresh.
  if (pathname.startsWith("/_next/")) return true;
  // Host e2e rewrites /api/* to uvicorn; JWT is checked by FastAPI, not Edge.
  if (pathname.startsWith("/api/")) return true;
  if (PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
    return true;
  }
  return PUBLIC_STATIC.test(pathname);
}

/** Official @supabase/ssr: keep refreshed auth cookies when creating a new response. */
function withSupabaseCookies(
  target: NextResponse,
  supabaseResponse: NextResponse,
): NextResponse {
  supabaseResponse.cookies.getAll().forEach(({ name, value, ...options }) => {
    target.cookies.set(name, value, options);
  });
  return target;
}

export async function middleware(request: NextRequest): Promise<NextResponse> {
  const { pathname } = request.nextUrl;

  // Refresh Supabase cookies when configured (no-op if env missing).
  // Must run before any redirect so Set-Cookie from token refresh is preserved.
  const supabaseResponse = await updateSession(request);

  // Never allow credentials in URL — strip and redirect (logs, referrers, history).
  if (pathname === "/login" && urlHasSensitiveLoginQueryParams(request.nextUrl)) {
    const safeLogin = stripSensitiveLoginQueryParams(request.nextUrl);
    return withSupabaseCookies(NextResponse.redirect(safeLogin), supabaseResponse);
  }

  if (isPublicPath(pathname)) {
    return supabaseResponse;
  }

  const tokenFromCookie = request.cookies.get("access_token")?.value;
  const authHeader = request.headers.get("authorization");
  const tokenFromHeader = authHeader?.startsWith("Bearer ")
    ? authHeader.slice(7)
    : null;

  const token = tokenFromCookie || tokenFromHeader;

  if (!token) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("from", pathname);
    // Only `from` is allowed on login redirects — never forward other query params.
    return withSupabaseCookies(
      NextResponse.redirect(stripSensitiveLoginQueryParams(loginUrl)),
      supabaseResponse,
    );
  }

  return supabaseResponse;
}

export const config = {
  // Skip middleware for Next.js internals and all static assets (CSS, JS, fonts, images)
  matcher: [
    "/((?!_next|favicon.ico|robots.txt|logo\\.png|.*\\.(?:png|jpg|jpeg|gif|svg|ico|webp|css|js|woff2?|ttf|eot|map)).*)",
  ],
};
