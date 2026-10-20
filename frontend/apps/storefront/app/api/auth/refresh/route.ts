import { NextResponse } from 'next/server';
import { requestId } from '@neomarket/telemetry';

const ACCESS_COOKIE = process.env.NODE_ENV === 'production' ? '__Host-nm_access' : 'nm_access';
const REFRESH_COOKIE = process.env.NODE_ENV === 'production' ? '__Host-nm_refresh' : 'nm_refresh';
function problem(title: string, status: number, rid: string) { return NextResponse.json({ type: 'about:blank', title, status, requestId: rid }, { status, headers: { 'Content-Type': 'application/problem+json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } }); }
function cookie(request: Request, name: string) { return request.headers.get('cookie')?.match(new RegExp(`(?:^|;\\s*)${name}=([^;]+)`))?.[1]; }
function trusted(request: Request) { const expected = process.env.NEOMARKET_PUBLIC_ORIGIN?.replace(/\/$/, ''); const origin = request.headers.get('origin'); return !(origin && (!expected || origin !== expected)) && request.headers.get('sec-fetch-site') !== 'cross-site'; }

export async function POST(request: Request) {
  const rid = requestId(request.headers.get('x-request-id')); const base = process.env.NEOMARKET_B2C_URL; const refresh = cookie(request, REFRESH_COOKIE);
  if (!trusted(request)) return problem('Request origin is not trusted', 403, rid);
  if (!base || !refresh) return problem('Refresh session is unavailable', 401, rid);
  try {
    const upstream = await fetch(`${base.replace(/\/$/, '')}/api/v1/auth/refresh`, { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Request-ID': rid }, body: JSON.stringify({ refresh_token: refresh }), cache: 'no-store' });
    const payload = await upstream.json().catch(() => null) as { access_token?: unknown; refresh_token?: unknown; expires_in?: unknown } | null;
    if (!upstream.ok || !payload || typeof payload.access_token !== 'string') return problem('Refresh session expired', 401, rid);
    const response = NextResponse.json({ authenticated: true }, { headers: { 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
    response.cookies.set(ACCESS_COOKIE, payload.access_token, { httpOnly: true, secure: process.env.NODE_ENV === 'production', sameSite: 'lax', path: '/', maxAge: Math.max(60, Number(payload.expires_in) || 900) });
    if (typeof payload.refresh_token === 'string' && payload.refresh_token.length > 0) response.cookies.set(REFRESH_COOKIE, payload.refresh_token, { httpOnly: true, secure: process.env.NODE_ENV === 'production', sameSite: 'lax', path: '/', maxAge: 60 * 60 * 24 * 30 });
    return response;
  } catch { return problem('Authentication service unavailable', 503, rid); }
}
