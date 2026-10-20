import { NextResponse } from 'next/server';
import { requestId } from '@neomarket/telemetry';

export async function DELETE(request: Request, context: { params: Promise<{ addressId: string }> }) {
  const rid = requestId(request.headers.get('x-request-id')); const base = process.env.NEOMARKET_B2C_URL;
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_access|nm_access)=([^;]+)/)?.[1];
  const csrf = request.headers.get('cookie')?.match(/(?:^|;\s*)nm_csrf=([^;]+)/)?.[1];
  const addressId = (await context.params).addressId;
  const origin = request.headers.get('origin'); const expected = process.env.NEOMARKET_PUBLIC_ORIGIN?.replace(/\/$/, ''); const localOrigin = new URL(request.url).origin;
  if (!token) return NextResponse.json({ type: 'about:blank', title: 'Buyer authentication is required', status: 401, requestId: rid }, { status: 401 });
  if (!base || !/^[0-9a-f-]{36}$/i.test(addressId)) return NextResponse.json({ type: 'about:blank', title: 'Invalid address', status: 400, requestId: rid }, { status: 400 });
  const configuredOrigin = Boolean(origin && expected && origin === expected);
  const sameOriginDevelopment = process.env.NODE_ENV !== 'production' && origin === localOrigin;
  if ((origin && !configuredOrigin && !sameOriginDevelopment) || request.headers.get('sec-fetch-site') === 'cross-site' || !csrf || request.headers.get('x-csrf-token') !== csrf) return NextResponse.json({ type: 'about:blank', title: 'CSRF validation failed', status: 403, requestId: rid }, { status: 403 });
  const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const upstream = await fetch(`${base.replace(/\/$/, '')}/api/v1/addresses/${addressId}`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}`, Accept: 'application/json', 'X-Request-ID': rid }, cache: 'no-store', signal: controller.signal });
    if (!upstream.ok) return NextResponse.json({ type: 'about:blank', title: upstream.status === 404 ? 'Address is not available' : 'Address service is temporarily unavailable', status: upstream.status, requestId: rid }, { status: upstream.status, headers: { 'Content-Type': 'application/problem+json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
    return new NextResponse(upstream.status === 204 ? null : await upstream.text(), { status: upstream.status, headers: { 'Content-Type': upstream.headers.get('content-type') ?? 'application/json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
  } catch (error) { return NextResponse.json({ type: 'about:blank', title: error instanceof DOMException && error.name === 'AbortError' ? 'Address request timed out' : 'Address service is temporarily unavailable', status: 503, requestId: rid }, { status: 503, headers: { 'Content-Type': 'application/problem+json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } }); }
  finally { clearTimeout(timeout); }
}
