import { NextResponse } from 'next/server';
import { requestId } from '@neomarket/telemetry';

export async function GET(request: Request) {
  const rid = requestId(request.headers.get('x-request-id')); const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_access|nm_access)=([^;]+)/)?.[1]; const base = process.env.NEOMARKET_B2C_URL;
  if (!token) return NextResponse.json({ type: 'about:blank', title: 'Buyer authentication is required', status: 401, requestId: rid }, { status: 401 });
  if (!base) return NextResponse.json({ type: 'about:blank', title: 'Order service is not configured', status: 503, requestId: rid }, { status: 503 });
  const incoming = new URL(request.url); const query = new URLSearchParams();
  for (const name of ['limit', 'offset', 'status']) { const value = incoming.searchParams.get(name); if (value && value.length <= 64) query.set(name, value); }
  const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const upstream = await fetch(`${base.replace(/\/$/, '')}/api/v1/orders?${query}`, { headers: { Accept: 'application/json', Authorization: `Bearer ${token}`, 'X-Request-ID': rid }, cache: 'no-store', signal: controller.signal });
    if (!upstream.ok) {
      const title = upstream.status === 401 || upstream.status === 403 ? 'Buyer session is not authorized' : 'Orders are temporarily unavailable';
      return NextResponse.json({ type: 'about:blank', title, status: upstream.status, requestId: rid }, { status: upstream.status, headers: { 'Content-Type': 'application/problem+json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
    }
    return new NextResponse(await upstream.text(), { status: upstream.status, headers: { 'Content-Type': upstream.headers.get('content-type') ?? 'application/json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
  } catch (error) {
    return NextResponse.json({ type: 'about:blank', title: error instanceof DOMException && error.name === 'AbortError' ? 'Orders request timed out' : 'Orders are temporarily unavailable', status: 503, requestId: rid }, { status: 503, headers: { 'Content-Type': 'application/problem+json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
  } finally { clearTimeout(timeout); }
}
