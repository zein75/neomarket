import { NextResponse } from 'next/server';
import { requestId } from '@neomarket/telemetry';

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
function problem(title: string, status: number, rid: string) { return NextResponse.json({ type: 'about:blank', title, status, requestId: rid }, { status, headers: { 'Content-Type': 'application/problem+json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } }); }
function csrfValid(request: Request) {
  const expected = process.env.NEOMARKET_PUBLIC_ORIGIN?.replace(/\/$/, ''); const origin = request.headers.get('origin'); const localOrigin = new URL(request.url).origin;
  const trustedOrigin = !origin || origin === expected || (process.env.NODE_ENV !== 'production' && origin === localOrigin);
  return trustedOrigin && request.headers.get('sec-fetch-site') !== 'cross-site' && request.headers.get('cookie')?.match(/(?:^|;\s*)nm_csrf=([^;]+)/)?.[1] === request.headers.get('x-csrf-token');
}

export async function POST(request: Request, context: { params: Promise<{ productId: string }> }) {
  const rid = requestId(request.headers.get('x-request-id')); const { productId } = await context.params;
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_access|nm_access)=([^;]+)/)?.[1]; const base = process.env.NEOMARKET_B2C_URL;
  if (!uuid.test(productId)) return problem('Invalid product id', 400, rid);
  if (!csrfValid(request)) return problem('CSRF validation failed', 403, rid);
  if (!token) return problem('Buyer authentication is required', 401, rid);
  if (!base) return problem('Favorites service is not configured', 503, rid);
  const response = await fetch(`${base.replace(/\/$/, '')}/api/v1/favorites/${productId}`, { method: 'POST', headers: { Accept: 'application/json', Authorization: `Bearer ${token}`, 'X-Request-ID': rid }, cache: 'no-store' });
  return new NextResponse(await response.text(), { status: response.status, headers: { 'Content-Type': response.headers.get('content-type') ?? 'application/json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
}

export async function DELETE(request: Request, context: { params: Promise<{ productId: string }> }) {
  const rid = requestId(request.headers.get('x-request-id')); const { productId } = await context.params;
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_access|nm_access)=([^;]+)/)?.[1]; const base = process.env.NEOMARKET_B2C_URL;
  if (!uuid.test(productId)) return problem('Invalid product id', 400, rid);
  if (!csrfValid(request)) return problem('CSRF validation failed', 403, rid);
  if (!token) return problem('Buyer authentication is required', 401, rid);
  if (!base) return problem('Favorites service is not configured', 503, rid);
  const response = await fetch(`${base.replace(/\/$/, '')}/api/v1/favorites/${productId}`, { method: 'DELETE', headers: { Accept: 'application/json', Authorization: `Bearer ${token}`, 'X-Request-ID': rid }, cache: 'no-store' });
  return new NextResponse(null, { status: response.status, headers: { 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
}
