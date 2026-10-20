import { NextResponse } from 'next/server';

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const problem = (type: string, title: string, status: number, rid: string) => NextResponse.json({ type, title, status, requestId: rid }, { status, headers: { 'Content-Type': 'application/problem+json', 'X-Request-ID': rid, 'Cache-Control': 'no-store' } });

export async function GET(request: Request, context: { params: Promise<{ categoryId: string }> }) {
  const { categoryId } = await context.params;
  const rid = request.headers.get('x-request-id') ?? crypto.randomUUID();
  const base = process.env.NEOMARKET_B2C_URL;
  if (!uuid.test(categoryId)) return problem('https://neomarket.dev/problems/invalid-category-id', 'Invalid category id', 400, rid);
  if (!base) return problem('https://neomarket.dev/problems/category-not-configured', 'Category service is not configured', 503, rid);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2500);
  try {
    const response = await fetch(`${base.replace(/\/$/, '')}/api/v1/categories/${categoryId}`, { headers: { Accept: 'application/json', 'x-request-id': rid }, cache: 'no-store', signal: controller.signal });
    return new NextResponse(await response.text(), { status: response.status, headers: { 'content-type': response.headers.get('content-type') ?? 'application/json', 'cache-control': 'no-store', 'X-Request-ID': rid } });
  } catch { return problem('https://neomarket.dev/problems/category-unavailable', 'Category service unavailable', 503, rid); }
  finally { clearTimeout(timeout); }
}
