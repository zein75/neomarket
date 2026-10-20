import { NextResponse } from 'next/server';
import { requestId } from '@neomarket/telemetry';

export async function GET(request: Request) {
  const upstream = process.env.NEOMARKET_B2C_URL;
  const rid = requestId(request.headers.get('x-request-id'));
  if (!upstream) return NextResponse.json({ type: 'not-configured', title: 'Catalog is not configured', status: 503 }, { status: 503 });
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2500);
  try {
    const response = await fetch(`${upstream.replace(/\/$/, '')}/api/v1/catalog/facets`, { headers: { Accept: 'application/json', 'X-Request-ID': rid }, signal: controller.signal, cache: 'no-store' });
    return new NextResponse(await response.text(), { status: response.status, headers: { 'content-type': response.headers.get('content-type') ?? 'application/json', 'cache-control': 'no-store', 'X-Request-ID': rid } });
  } catch {
    return NextResponse.json({ type: 'upstream-unavailable', title: 'Catalog facets unavailable', status: 503, requestId: rid }, { status: 503, headers: { 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
  } finally { clearTimeout(timeout); }
}
