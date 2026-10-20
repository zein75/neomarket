import { NextResponse } from 'next/server';
import { isSessionResponse } from '@neomarket/api-types';
import { requestId } from '@neomarket/telemetry';

const problem = (type: string, title: string, status: number, rid: string) => NextResponse.json({ type, title, status, requestId: rid }, { status, headers: { 'Content-Type': 'application/problem+json', 'X-Request-ID': rid, 'Cache-Control': 'no-store' } });
const refreshCookieName = process.env.NODE_ENV === 'production' ? '__Host-nm_refresh' : 'nm_refresh';

async function rotateAccess(base: string, request: Request, rid: string) {
  const refresh = request.headers.get('cookie')?.match(new RegExp(`(?:^|;\\s*)${refreshCookieName}=([^;]+)`))?.[1];
  if (!refresh) return null;
  const response = await fetch(`${base.replace(/\/$/, '')}/api/v1/auth/refresh`, { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Request-ID': rid }, body: JSON.stringify({ refresh_token: refresh }), cache: 'no-store' });
  const payload = await response.json().catch(() => null) as { access_token?: unknown; refresh_token?: unknown; expires_in?: unknown } | null;
  if (!response.ok || !payload || typeof payload.access_token !== 'string') return null;
  return payload;
}

export async function GET(request: Request) {
  const sessionService = process.env.NEOMARKET_SESSION_SERVICE_URL;
  const b2cService = process.env.NEOMARKET_B2C_URL;
  const rid = requestId(request.headers.get('x-request-id'));
  let accessCookie = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_access|nm_access)=([^;]+)/)?.[1];
  if (!sessionService && !b2cService) return problem('https://neomarket.dev/problems/session-not-configured', 'Session service is not configured', 503, rid);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2000);
  try {
    // Prefer the opaque session provider. The B2C fallback keeps the checkout
    // boundary authenticated when the deployment has no separate session
    // service: the JWT remains server-only in an HttpOnly cookie.
    const cookieHeader = (request.headers.get('cookie') ?? '').split(';').map((part) => part.trim()).filter((part) => /^(?:__Host-nm_sid|nm_session|nm_guest_session)=/.test(part)).join('; ');
    let refreshed: { access_token?: unknown; refresh_token?: unknown; expires_in?: unknown } | null = null;
    let upstream = sessionService
      ? await fetch(`${sessionService.replace(/\/$/, '')}/session`, { headers: { Accept: 'application/json', ...(cookieHeader ? { cookie: cookieHeader } : {}), 'X-Request-ID': rid }, credentials: 'include', cache: 'no-store', signal: controller.signal })
      : await fetch(`${b2cService!.replace(/\/$/, '')}/api/v1/auth/me`, { headers: { Accept: 'application/json', ...(accessCookie ? { Authorization: `Bearer ${accessCookie}` } : {}), 'X-Request-ID': rid }, cache: 'no-store', signal: controller.signal });
    if (!sessionService && upstream.status === 401) {
      refreshed = await rotateAccess(b2cService!, request, rid);
      if (refreshed && typeof refreshed.access_token === 'string') {
        accessCookie = refreshed.access_token;
        upstream = await fetch(`${b2cService!.replace(/\/$/, '')}/api/v1/auth/me`, { headers: { Accept: 'application/json', Authorization: `Bearer ${accessCookie}`, 'X-Request-ID': rid }, cache: 'no-store', signal: controller.signal });
      }
    }
    const payload: unknown = await upstream.json().catch(() => null);
    if (sessionService) {
      if (!isSessionResponse(payload)) return problem('https://neomarket.dev/problems/invalid-session', 'Invalid session response', 502, rid);
      if (payload.authenticated || !accessCookie || !b2cService) return NextResponse.json(payload, { status: upstream.status, headers: { 'cache-control': 'no-store', 'X-Request-ID': rid } });
      // A login issued by the B2C auth adapter can be resolved even when the
      // optional session provider has not yet exchanged its opaque cookie.
      const authProbe = await fetch(`${b2cService.replace(/\/$/, '')}/api/v1/auth/me`, { headers: { Accept: 'application/json', Authorization: `Bearer ${accessCookie}`, 'X-Request-ID': rid }, cache: 'no-store', signal: controller.signal });
      const user = await authProbe.json().catch(() => null) as { id?: unknown; first_name?: string | null; last_name?: string | null } | null;
      if (!authProbe.ok || !user || typeof user.id !== 'string') return NextResponse.json(payload, { status: upstream.status, headers: { 'cache-control': 'no-store', 'X-Request-ID': rid } });
      return NextResponse.json({ authenticated: true, principal: { id: user.id, role: 'buyer', displayName: [user.first_name, user.last_name].filter(Boolean).join(' ') || undefined } }, { status: 200, headers: { 'cache-control': 'no-store', 'X-Request-ID': rid } });
    }
    if (!upstream.ok || !payload || typeof payload !== 'object' || typeof (payload as { id?: unknown }).id !== 'string') return NextResponse.json({ authenticated: false }, { status: 200, headers: { 'cache-control': 'no-store', 'X-Request-ID': rid } });
    const user = payload as { id: string; first_name?: string | null; last_name?: string | null };
    const result = NextResponse.json({ authenticated: true, principal: { id: user.id, role: 'buyer', displayName: [user.first_name, user.last_name].filter(Boolean).join(' ') || undefined } }, { status: 200, headers: { 'cache-control': 'no-store', 'X-Request-ID': rid } });
    if (refreshed && typeof refreshed.access_token === 'string') result.cookies.set(process.env.NODE_ENV === 'production' ? '__Host-nm_access' : 'nm_access', refreshed.access_token, { httpOnly: true, secure: process.env.NODE_ENV === 'production', sameSite: 'lax', path: '/', maxAge: Math.max(60, Number(refreshed.expires_in) || 900) });
    if (refreshed && typeof refreshed.refresh_token === 'string') result.cookies.set(refreshCookieName, refreshed.refresh_token, { httpOnly: true, secure: process.env.NODE_ENV === 'production', sameSite: 'lax', path: '/', maxAge: 60 * 60 * 24 * 30 });
    return result;
  } catch {
    return problem('https://neomarket.dev/problems/session-unavailable', 'Session service unavailable', 503, rid);
  } finally {
    clearTimeout(timeout);
  }
}
