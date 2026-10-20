import { NextResponse } from 'next/server';
import { requestId } from '@neomarket/telemetry';

const ACCESS_COOKIE = process.env.NODE_ENV === 'production' ? '__Host-nm_access' : 'nm_access';
const REFRESH_COOKIE = process.env.NODE_ENV === 'production' ? '__Host-nm_refresh' : 'nm_refresh';

function problem(type: string, title: string, status: number, rid: string) {
  return NextResponse.json({ type, title, status, requestId: rid }, {
    status,
    headers: { 'Content-Type': 'application/problem+json', 'Cache-Control': 'no-store', 'X-Request-ID': rid },
  });
}

function trustedOrigin(request: Request) {
  const origin = request.headers.get('origin');
  const expected = process.env.NEOMARKET_PUBLIC_ORIGIN?.replace(/\/$/, '');
  const localOrigin = new URL(request.url).origin;
  if (origin && origin !== expected && !(process.env.NODE_ENV !== 'production' && origin === localOrigin)) return false;
  return request.headers.get('sec-fetch-site') !== 'cross-site';
}

function guestSessionHeader(request: Request) {
  const value = request.headers.get('cookie')?.match(/(?:^|;\s*)nm_guest_session=([^;]+)/)?.[1];
  return value && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value) ? value : undefined;
}

export async function POST(request: Request) {
  const rid = requestId(request.headers.get('x-request-id'));
  if (!trustedOrigin(request)) return problem('https://neomarket.dev/problems/csrf-origin', 'Request origin is not trusted', 403, rid);
  const base = process.env.NEOMARKET_B2C_URL;
  if (!base) return problem('https://neomarket.dev/problems/auth-not-configured', 'Authentication service is not configured', 503, rid);

  const body = await request.json().catch(() => null) as { email?: unknown; password?: unknown } | null;
  if (!body || typeof body.email !== 'string' || typeof body.password !== 'string' || body.email.length > 320 || body.password.length < 8) {
    return problem('https://neomarket.dev/problems/invalid-auth-request', 'Email and password are required', 400, rid);
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const guestSessionId = guestSessionHeader(request);
    const upstream = await fetch(`${base.replace(/\/$/, '')}/api/v1/auth/login`, {
      method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Request-ID': rid, ...(guestSessionId ? { 'X-Session-ID': guestSessionId } : {}) },
      body: JSON.stringify({ email: body.email, password: body.password }), cache: 'no-store', signal: controller.signal,
    });
    const payload = await upstream.json().catch(() => null) as { access_token?: unknown; refresh_token?: unknown; expires_in?: unknown } | null;
    if (!upstream.ok || !payload || typeof payload.access_token !== 'string') {
      const title = upstream.status === 401 || upstream.status === 403 ? 'Invalid credentials' : upstream.status === 429 ? 'Too many attempts' : 'Authentication failed';
      return problem('https://neomarket.dev/problems/authentication-failed', title, upstream.status || 502, rid);
    }
    const response = NextResponse.json({ authenticated: true }, { headers: { 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
    response.cookies.set(ACCESS_COOKIE, payload.access_token, { httpOnly: true, secure: process.env.NODE_ENV === 'production', sameSite: 'lax', path: '/', maxAge: Math.max(60, Number(payload.expires_in) || 900) });
    if (typeof payload.refresh_token === 'string' && payload.refresh_token.length > 0) response.cookies.set(REFRESH_COOKIE, payload.refresh_token, { httpOnly: true, secure: process.env.NODE_ENV === 'production', sameSite: 'lax', path: '/', maxAge: 60 * 60 * 24 * 30 });
    return response;
  } catch (error) {
    return problem('https://neomarket.dev/problems/auth-unavailable', error instanceof DOMException && error.name === 'AbortError' ? 'Authentication timed out' : 'Authentication unavailable', 503, rid);
  } finally { clearTimeout(timeout); }
}
