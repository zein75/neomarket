import { NextResponse } from 'next/server';
import { requestId } from '@neomarket/telemetry';

export async function GET(request: Request) {
  const rid = requestId(request.headers.get('x-request-id')); const base = process.env.NEOMARKET_B2C_URL;
  if (!base) return NextResponse.json({ type: 'about:blank', title: 'Home service is not configured', status: 503, requestId: rid }, { status: 503, headers: { 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
  const root = base.replace(/\/$/, '');
  const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const [banners, collections, categories] = await Promise.all([
      fetch(`${root}/api/v1/home/banners`, { headers: { Accept: 'application/json', 'X-Request-ID': rid }, cache: 'no-store', signal: controller.signal }),
      fetch(`${root}/api/v1/main/collections?limit=12&offset=0`, { headers: { Accept: 'application/json', 'X-Request-ID': rid }, cache: 'no-store', signal: controller.signal }),
      fetch(`${root}/api/v1/categories`, { headers: { Accept: 'application/json', 'X-Request-ID': rid }, cache: 'no-store', signal: controller.signal }),
    ]);
    if (!banners.ok || !collections.ok || !categories.ok) return NextResponse.json({ type: 'about:blank', title: 'Home service unavailable', status: 502, requestId: rid }, { status: 502, headers: { 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
    return NextResponse.json({ banners: await banners.json(), collections: await collections.json(), categories: await categories.json() }, { headers: { 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
  } catch (error) { return NextResponse.json({ type: 'about:blank', title: error instanceof DOMException && error.name === 'AbortError' ? 'Home request timed out' : 'Home service unavailable', status: 503, requestId: rid }, { status: 503, headers: { 'Cache-Control': 'no-store', 'X-Request-ID': rid } }); }
  finally { clearTimeout(timeout); }
}
