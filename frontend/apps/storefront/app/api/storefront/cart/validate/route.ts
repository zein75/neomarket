import { NextResponse } from 'next/server';
import { requestId } from '@neomarket/telemetry';

function problem(type: string, title: string, status: number, rid: string) {
  return NextResponse.json({ type, title, status, requestId: rid }, { status, headers: { 'Content-Type': 'application/problem+json', 'X-Request-ID': rid, 'Cache-Control': 'no-store' } });
}

function accessHeader(request: Request) {
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_access|nm_access)=([^;]+)/)?.[1];
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function POST(request: Request) {
  const rid = requestId(request.headers.get('x-request-id'));
  const expectedOrigin = process.env.NEOMARKET_PUBLIC_ORIGIN?.replace(/\/$/, '');
  const origin = request.headers.get('origin');
  const localOrigin = new URL(request.url).origin;
  const isConfiguredOrigin = Boolean(origin && expectedOrigin && origin === expectedOrigin);
  const isLocalDevelopmentOrigin = process.env.NODE_ENV !== 'production' && origin === localOrigin;
  if ((origin && !isConfiguredOrigin && !isLocalDevelopmentOrigin) || request.headers.get('sec-fetch-site') === 'cross-site') return problem('https://neomarket.dev/problems/csrf-origin', 'Request origin is not trusted', 403, rid);
  const csrfCookie = request.headers.get('cookie')?.match(/(?:^|;\s*)nm_csrf=([^;]+)/)?.[1];
  if (!csrfCookie || csrfCookie !== request.headers.get('x-csrf-token')) return problem('https://neomarket.dev/problems/csrf', 'CSRF validation failed', 403, rid);
  const sessionId = request.headers.get('cookie')?.match(/(?:^|;\s*)nm_guest_session=([^;]+)/)?.[1];
  const base = process.env.NEOMARKET_B2C_URL;
  if (!base || !sessionId) return problem('https://neomarket.dev/problems/cart-not-configured', 'Cart session is not available', 503, rid);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2500);
  try {
    const upstream = await fetch(`${base.replace(/\/$/, '')}/api/v1/cart/validate`, { method: 'POST', headers: { Accept: 'application/json', 'X-Session-Id': sessionId, 'X-Request-ID': rid, ...accessHeader(request) }, cache: 'no-store', signal: controller.signal });
    const body = await upstream.text();
    return new NextResponse(body, { status: upstream.status, headers: { 'content-type': upstream.headers.get('content-type') ?? 'application/json', 'cache-control': 'no-store', 'X-Request-ID': rid } });
  } catch {
    return problem('https://neomarket.dev/problems/cart-unavailable', 'Cart service unavailable', 503, rid);
  } finally { clearTimeout(timeout); }
}
