import { NextResponse } from 'next/server';
const problem = (type: string, title: string, status: number, rid: string) => NextResponse.json({ type, title, status, requestId: rid }, { status, headers: { 'Content-Type': 'application/problem+json', 'X-Request-ID': rid, 'Cache-Control': 'no-store' } });

export async function GET(request: Request) {
  const base = process.env.NEOMARKET_B2C_URL;
  const rid = request.headers.get('x-request-id') ?? crypto.randomUUID();
  if (!base) return problem('https://neomarket.dev/problems/category-not-configured', 'Category service is not configured', 503, rid);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2500);
  try {
    const response = await fetch(`${base.replace(/\/$/, '')}/api/v1/categories`, { headers: { Accept: 'application/json', 'x-request-id': rid }, cache: 'no-store', signal: controller.signal });
    return new NextResponse(await response.text(), { status: response.status, headers: { 'content-type': response.headers.get('content-type') ?? 'application/json', 'cache-control': 'no-store', 'X-Request-ID': rid } });
  } catch { return problem('https://neomarket.dev/problems/category-unavailable', 'Category service unavailable', 503, rid); }
  finally { clearTimeout(timeout); }
}
