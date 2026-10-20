import { NextResponse } from 'next/server';
import { requestId } from '@neomarket/telemetry';

function problem(type: string, title: string, status: number, rid: string) {
  return NextResponse.json({ type, title, status, requestId: rid }, { status, headers: { 'Content-Type': 'application/problem+json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
}
function cookie(request: Request, name: string) { return request.headers.get('cookie')?.match(new RegExp(`(?:^|;\\s*)${name}=([^;]+)`))?.[1]; }
function access(request: Request) { return cookie(request, '__Host-nm_access') ?? cookie(request, 'nm_access'); }
function trusted(request: Request) {
  const origin = request.headers.get('origin');
  const expected = process.env.NEOMARKET_PUBLIC_ORIGIN?.replace(/\/$/, '');
  const localOrigin = new URL(request.url).origin;
  const configuredOrigin = Boolean(origin && expected && origin === expected);
  const sameOriginDevelopment = process.env.NODE_ENV !== 'production' && origin === localOrigin;
  return (!origin || configuredOrigin || sameOriginDevelopment) && request.headers.get('sec-fetch-site') !== 'cross-site';
}

async function proxy(request: Request, method: 'GET' | 'POST') {
  const rid = requestId(request.headers.get('x-request-id')); const token = access(request); const base = process.env.NEOMARKET_B2C_URL;
  if (!token) return problem('https://neomarket.dev/problems/auth-required', 'Buyer authentication is required', 401, rid);
  if (!base) return problem('https://neomarket.dev/problems/addresses-not-configured', 'Address service is not configured', 503, rid);
  if (method === 'POST') {
    if (!trusted(request)) return problem('https://neomarket.dev/problems/csrf-origin', 'Request origin is not trusted', 403, rid);
    const csrf = cookie(request, 'nm_csrf'); if (!csrf || request.headers.get('x-csrf-token') !== csrf) return problem('https://neomarket.dev/problems/csrf', 'CSRF validation failed', 403, rid);
  }
  const body = method === 'POST' ? await request.text() : undefined;
  const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const upstream = await fetch(`${base.replace(/\/$/, '')}/api/v1/addresses`, { method, headers: { Accept: 'application/json', Authorization: `Bearer ${token}`, 'X-Request-ID': rid, ...(body ? { 'Content-Type': 'application/json' } : {}) }, ...(body ? { body } : {}), cache: 'no-store', signal: controller.signal });
    if (!upstream.ok) return problem('https://neomarket.dev/problems/address-service', upstream.status === 401 || upstream.status === 403 ? 'Buyer session is not authorized' : 'Address service is temporarily unavailable', upstream.status, rid);
    return new NextResponse(await upstream.text(), { status: upstream.status, headers: { 'Content-Type': upstream.headers.get('content-type') ?? 'application/json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
  } catch (error) { return problem('https://neomarket.dev/problems/address-service', error instanceof DOMException && error.name === 'AbortError' ? 'Address request timed out' : 'Address service is temporarily unavailable', 503, rid); }
  finally { clearTimeout(timeout); }
}
export function GET(request: Request) { return proxy(request, 'GET'); }
export function POST(request: Request) { return proxy(request, 'POST'); }
