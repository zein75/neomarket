import { NextResponse } from 'next/server';
import { requestId } from '@neomarket/telemetry';

const ACCESS_COOKIE = process.env.NODE_ENV === 'production' ? '__Host-nm_access' : 'nm_access';
const REFRESH_COOKIE = process.env.NODE_ENV === 'production' ? '__Host-nm_refresh' : 'nm_refresh';

function guestSessionHeader(request: Request) {
  const value = request.headers.get('cookie')?.match(/(?:^|;\s*)nm_guest_session=([^;]+)/)?.[1];
  return value && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value) ? value : undefined;
}

export async function POST(request: Request) {
  const rid = requestId(request.headers.get('x-request-id'));
  const origin = request.headers.get('origin');
  const expected = process.env.NEOMARKET_PUBLIC_ORIGIN?.replace(/\/$/, '');
  const localOrigin = new URL(request.url).origin;
  const trusted = !origin || origin === expected || (process.env.NODE_ENV !== 'production' && origin === localOrigin);
  if (!trusted || request.headers.get('sec-fetch-site') === 'cross-site') return NextResponse.json({ type: 'about:blank', title: 'Request origin is not trusted', status: 403, requestId: rid }, { status: 403, headers: { 'Content-Type': 'application/problem+json' } });
  const base = process.env.NEOMARKET_B2C_URL;
  if (!base) return NextResponse.json({ type: 'about:blank', title: 'Authentication service is not configured', status: 503, requestId: rid }, { status: 503, headers: { 'Content-Type': 'application/problem+json' } });
  const body = await request.json().catch(() => null);
  if (!body || typeof body !== 'object' || typeof (body as { email?: unknown }).email !== 'string' || typeof (body as { password?: unknown }).password !== 'string' || String((body as { password?: unknown }).password).length < 8) return NextResponse.json({ type: 'about:blank', title: 'Invalid registration request', status: 400, requestId: rid }, { status: 400, headers: { 'Content-Type': 'application/problem+json' } });
  const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const upstream = await fetch(`${base.replace(/\/$/, '')}/api/v1/auth/register`, { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Request-ID': rid }, body: JSON.stringify(body), cache: 'no-store', signal: controller.signal });
    if (!upstream.ok) {
      const title = upstream.status === 409 ? 'Account already exists' : upstream.status === 429 ? 'Too many attempts' : 'Registration failed';
      return NextResponse.json({ type: 'about:blank', title, status: upstream.status, requestId: rid }, { status: upstream.status, headers: { 'Content-Type': 'application/problem+json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
    }
    // Registration is immediately followed by a server-side login. This keeps
    // the user in one coherent flow and avoids redirecting to a private page
    // without the HttpOnly session cookies.
    const guestSessionId = guestSessionHeader(request);
    const login = await fetch(`${base.replace(/\/$/, '')}/api/v1/auth/login`, {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Request-ID': rid, ...(guestSessionId ? { 'X-Session-ID': guestSessionId } : {}) },
      body: JSON.stringify({ email: (body as { email: string }).email, password: (body as { password: string }).password }),
      cache: 'no-store',
      signal: controller.signal,
    });
    const payload = await login.json().catch(() => null) as { access_token?: unknown; refresh_token?: unknown; expires_in?: unknown } | null;
    if (!login.ok || !payload || typeof payload.access_token !== 'string') {
      // The account was created, but do not pretend that authentication
      // succeeded. The client can send the user to the normal login form.
      return NextResponse.json({ registered: true, authenticated: false }, { status: 201, headers: { 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
    }
    const response = NextResponse.json({ registered: true, authenticated: true }, { status: 201, headers: { 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
    response.cookies.set(ACCESS_COOKIE, payload.access_token, { httpOnly: true, secure: process.env.NODE_ENV === 'production', sameSite: 'lax', path: '/', maxAge: Math.max(60, Number(payload.expires_in) || 900) });
    if (typeof payload.refresh_token === 'string' && payload.refresh_token.length > 0) response.cookies.set(REFRESH_COOKIE, payload.refresh_token, { httpOnly: true, secure: process.env.NODE_ENV === 'production', sameSite: 'lax', path: '/', maxAge: 60 * 60 * 24 * 30 });
    return response;
  } catch (error) {
    return NextResponse.json({ type: 'about:blank', title: error instanceof DOMException && error.name === 'AbortError' ? 'Registration timed out' : 'Registration unavailable', status: 503, requestId: rid }, { status: 503, headers: { 'Content-Type': 'application/problem+json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
  } finally { clearTimeout(timeout); }
}
