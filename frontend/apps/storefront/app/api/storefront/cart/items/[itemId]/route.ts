import { NextResponse } from 'next/server';
import { requestId } from '@neomarket/telemetry';

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function problem(type: string, title: string, status: number, rid: string) {
  return NextResponse.json({ type, title, status, requestId: rid }, { status, headers: { 'Content-Type': 'application/problem+json', 'X-Request-ID': rid, 'Cache-Control': 'no-store' } });
}

function accessHeader(request: Request) {
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_access|nm_access)=([^;]+)/)?.[1];
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function hasTrustedOrigin(request: Request) {
  const origin = request.headers.get('origin');
  const expectedOrigin = process.env.NEOMARKET_PUBLIC_ORIGIN?.replace(/\/$/, '');
  const localOrigin = new URL(request.url).origin;
  const isConfiguredOrigin = Boolean(origin && expectedOrigin && origin === expectedOrigin);
  const isLocalDevelopmentOrigin = process.env.NODE_ENV !== 'production' && origin === localOrigin;
  return (!origin || isConfiguredOrigin || isLocalDevelopmentOrigin)
    && request.headers.get('sec-fetch-site') !== 'cross-site';
}

export async function DELETE(request: Request, context: { params: Promise<{ itemId: string }> }) {
  const rid = requestId(request.headers.get('x-request-id'));
  const { itemId } = await context.params;
  if (!uuid.test(itemId)) return problem('https://neomarket.dev/problems/invalid-cart-item-id', 'Invalid cart item id', 400, rid);
  if (!hasTrustedOrigin(request)) return problem('https://neomarket.dev/problems/csrf-origin', 'Request origin is not trusted', 403, rid);
  const csrfCookie = request.headers.get('cookie')?.match(/(?:^|;\s*)nm_csrf=([^;]+)/)?.[1];
  if (!csrfCookie || csrfCookie !== request.headers.get('x-csrf-token')) return problem('https://neomarket.dev/problems/csrf', 'CSRF validation failed', 403, rid);
  const sessionId = request.headers.get('cookie')?.match(/(?:^|;\s*)nm_guest_session=([^;]+)/)?.[1];
  const base = process.env.NEOMARKET_B2C_URL;
  if (!base || !sessionId) return problem('https://neomarket.dev/problems/cart-not-configured', 'Cart session is not available', 503, rid);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2500);
  try {
    const upstream = await fetch(`${base.replace(/\/$/, '')}/api/v1/cart/items/${itemId}`, { method: 'DELETE', headers: { Accept: 'application/json', 'X-Session-Id': sessionId, 'X-Request-ID': rid, ...accessHeader(request) }, cache: 'no-store', signal: controller.signal });
    const body = await upstream.text();
    return new NextResponse(body, { status: upstream.status, headers: { 'content-type': upstream.headers.get('content-type') ?? 'application/json', 'cache-control': 'no-store', 'X-Request-ID': rid } });
  } catch {
    return problem('https://neomarket.dev/problems/cart-unavailable', 'Cart service unavailable', 503, rid);
  } finally { clearTimeout(timeout); }
}

export async function PATCH(request: Request, context: { params: Promise<{ itemId: string }> }) {
  const rid = requestId(request.headers.get('x-request-id'));
  const { itemId } = await context.params;
  if (!uuid.test(itemId)) return problem('https://neomarket.dev/problems/invalid-cart-item-id', 'Invalid cart item id', 400, rid);
  if (!hasTrustedOrigin(request)) return problem('https://neomarket.dev/problems/csrf-origin', 'Request origin is not trusted', 403, rid);
  const csrfCookie = request.headers.get('cookie')?.match(/(?:^|;\s*)nm_csrf=([^;]+)/)?.[1];
  if (!csrfCookie || csrfCookie !== request.headers.get('x-csrf-token')) return problem('https://neomarket.dev/problems/csrf', 'CSRF validation failed', 403, rid);
  const sessionId = request.headers.get('cookie')?.match(/(?:^|;\s*)nm_guest_session=([^;]+)/)?.[1];
  const base = process.env.NEOMARKET_B2C_URL;
  if (!base || !sessionId) return problem('https://neomarket.dev/problems/cart-not-configured', 'Cart session is not available', 503, rid);
  let payload: unknown;
  try { payload = await request.json(); } catch { return problem('https://neomarket.dev/problems/invalid-cart-item', 'Invalid cart item payload', 400, rid); }
  const quantity = payload && typeof payload === 'object' ? (payload as Record<string, unknown>).quantity : undefined;
  if (typeof quantity !== 'number' || !Number.isInteger(quantity) || quantity < 1 || quantity > 10000) return problem('https://neomarket.dev/problems/invalid-cart-item', 'Invalid cart item payload', 400, rid);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const upstream = await fetch(`${base.replace(/\/$/, '')}/api/v1/cart/items/${itemId}`, { method: 'PATCH', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Session-Id': sessionId, 'X-Request-ID': rid, ...accessHeader(request) }, body: JSON.stringify({ quantity }), cache: 'no-store', signal: controller.signal });
    const body = await upstream.text();
    return new NextResponse(body, { status: upstream.status, headers: { 'content-type': upstream.headers.get('content-type') ?? 'application/json', 'cache-control': 'no-store', 'X-Request-ID': rid } });
  } catch { return problem('https://neomarket.dev/problems/cart-unavailable', 'Cart service unavailable', 503, rid); }
  finally { clearTimeout(timeout); }
}
