import { NextResponse } from 'next/server';
import { requestId } from '@neomarket/telemetry';

const guestCookie = 'nm_guest_session';

function problem(type: string, title: string, status: number, requestIdValue?: string) {
  return NextResponse.json({ type, title, status, ...(requestIdValue ? { requestId: requestIdValue } : {}) }, { status, headers: { 'Content-Type': 'application/problem+json', ...(requestIdValue ? { 'X-Request-ID': requestIdValue } : {}), 'Cache-Control': 'no-store' } });
}

function upstreamConfig() {
  const base = process.env.NEOMARKET_B2C_URL;
  return base ? `${base.replace(/\/$/, '')}/api/v1/cart` : null;
}

function sessionId(request: Request) {
  const cookie = request.headers.get('cookie')?.match(/(?:^|;\s*)nm_guest_session=([^;]+)/)?.[1];
  return cookie ?? crypto.randomUUID();
}

function accessHeader(request: Request) {
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_access|nm_access)=([^;]+)/)?.[1];
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function applyGuestCookie(response: NextResponse, id: string, request: Request) {
  if (!request.headers.get('cookie')?.includes(`${guestCookie}=`)) response.cookies.set(guestCookie, id, { httpOnly: true, sameSite: 'lax', secure: process.env.NODE_ENV === 'production', path: '/' });
  return response;
}

function trustedMutationOrigin(request: Request) {
  const origin = request.headers.get('origin');
  const expected = process.env.NEOMARKET_PUBLIC_ORIGIN?.replace(/\/$/, '');
  const localOrigin = new URL(request.url).origin;
  const isConfiguredOrigin = Boolean(origin && expected && origin === expected);
  const isLocalDevelopmentOrigin = process.env.NODE_ENV !== 'production' && origin === localOrigin;
  if (origin && !isConfiguredOrigin && !isLocalDevelopmentOrigin) return false;
  const fetchSite = request.headers.get('sec-fetch-site');
  return fetchSite !== 'cross-site';
}

async function proxy(request: Request, method: 'GET' | 'DELETE') {
  const target = upstreamConfig();
  if (!target) return problem('https://neomarket.dev/problems/cart-not-configured', 'Cart service is not configured', 503);
  if (method === 'DELETE') {
    if (!trustedMutationOrigin(request)) return problem('https://neomarket.dev/problems/csrf-origin', 'Request origin is not trusted', 403);
    const csrfCookie = request.headers.get('cookie')?.match(/(?:^|;\s*)nm_csrf=([^;]+)/)?.[1];
    const csrfHeader = request.headers.get('x-csrf-token');
    if (!csrfCookie || !csrfHeader || csrfCookie !== csrfHeader) return problem('https://neomarket.dev/problems/csrf', 'CSRF validation failed', 403);
  }
  const id = sessionId(request);
  const rid = requestId(request.headers.get('x-request-id'));
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2500);
  try {
    const upstream = await fetch(target, { method, headers: { Accept: 'application/json', 'X-Session-Id': id, 'X-Request-ID': rid, ...accessHeader(request) }, cache: 'no-store', signal: controller.signal });
    const body = method === 'DELETE' && upstream.status === 204 ? null : await upstream.text();
    const response = new NextResponse(body, { status: upstream.status, headers: { 'content-type': upstream.headers.get('content-type') ?? 'application/json', 'cache-control': 'no-store', 'X-Request-ID': rid } });
    return applyGuestCookie(response, id, request);
  } catch {
    return applyGuestCookie(problem('https://neomarket.dev/problems/cart-unavailable', 'Cart service unavailable', 503, rid), id, request);
  } finally {
    clearTimeout(timeout);
  }
}

export function GET(request: Request) { return proxy(request, 'GET'); }
export function DELETE(request: Request) { return proxy(request, 'DELETE'); }
