import { NextResponse } from 'next/server';
import { requestId } from '@neomarket/telemetry';

export async function GET(request: Request, context: { params: Promise<{ orderId: string }> }) {
  return proxy(request, context, 'GET');
}
export async function POST(request: Request, context: { params: Promise<{ orderId: string }> }) {
  return proxy(request, context, 'POST');
}
async function proxy(request: Request, context: { params: Promise<{ orderId: string }> }, method: 'GET' | 'POST') {
  const rid = requestId(request.headers.get('x-request-id')); const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_access|nm_access)=([^;]+)/)?.[1]; const base = process.env.NEOMARKET_B2C_URL; const orderId = (await context.params).orderId;
  if (!token) return NextResponse.json({ type: 'about:blank', title: 'Buyer authentication is required', status: 401, requestId: rid }, { status: 401 });
  if (!base || !/^[0-9a-f-]{36}$/i.test(orderId)) return NextResponse.json({ type: 'about:blank', title: 'Invalid order', status: 400, requestId: rid }, { status: 400 });
  if (method === 'POST') { const csrf = request.headers.get('cookie')?.match(/(?:^|;\s*)nm_csrf=([^;]+)/)?.[1]; const origin = request.headers.get('origin'); const expected = process.env.NEOMARKET_PUBLIC_ORIGIN; if ((origin && (!expected || origin !== expected.replace(/\/$/, ''))) || request.headers.get('sec-fetch-site') === 'cross-site' || !csrf || csrf !== request.headers.get('x-csrf-token')) return NextResponse.json({ type: 'about:blank', title: 'CSRF validation failed', status: 403, requestId: rid }, { status: 403 }); }
  const target = `${base.replace(/\/$/, '')}/api/v1/orders/${orderId}${method === 'POST' ? '/cancel' : ''}`;
  const init: RequestInit = { method, cache: 'no-store', headers: { Accept: 'application/json', Authorization: `Bearer ${token}`, 'X-Request-ID': rid } };
  if (method === 'POST') {
    const idempotencyKey = request.headers.get('idempotency-key');
    if (!idempotencyKey || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(idempotencyKey)) return NextResponse.json({ type: 'about:blank', title: 'Idempotency-Key is required', status: 400, requestId: rid }, { status: 400 });
    init.headers = { ...init.headers as Record<string, string>, 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey };
    init.body = JSON.stringify(await request.json().catch(() => ({})));
  }
  const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 5000); init.signal = controller.signal;
  try {
    const upstream = await fetch(target, init);
    if (!upstream.ok) {
      const title = upstream.status === 401 || upstream.status === 403 ? 'Buyer session is not authorized' : upstream.status === 404 ? 'Order is not available' : method === 'POST' && upstream.status === 409 ? 'Order cancellation is not allowed' : 'Order service is temporarily unavailable';
      return NextResponse.json({ type: 'about:blank', title, status: upstream.status, requestId: rid }, { status: upstream.status, headers: { 'Content-Type': 'application/problem+json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
    }
    return new NextResponse(upstream.status === 204 ? null : await upstream.text(), { status: upstream.status, headers: { 'Content-Type': upstream.headers.get('content-type') ?? 'application/json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
  } catch (error) {
    return NextResponse.json({ type: 'about:blank', title: error instanceof DOMException && error.name === 'AbortError' ? 'Order request timed out' : 'Order service is temporarily unavailable', status: 503, requestId: rid }, { status: 503, headers: { 'Content-Type': 'application/problem+json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
  } finally { clearTimeout(timeout); }
}
