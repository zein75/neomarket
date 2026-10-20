import { NextResponse } from 'next/server';
import { requestId } from '@neomarket/telemetry';

const timeoutMs = 2500;

function problem(type: string, title: string, status: number, rid?: string) {
  return NextResponse.json({ type, title, status, ...(rid ? { requestId: rid } : {}) }, { status, headers: { 'Content-Type': 'application/problem+json', ...(rid ? { 'X-Request-ID': rid } : {}), 'Cache-Control': 'no-store' } });
}

export async function GET(request: Request) {
  const upstream = process.env.NEOMARKET_B2C_URL;
  const rid = requestId(request.headers.get('x-request-id'));
  if (!upstream) return problem('https://neomarket.dev/problems/not-configured', 'Catalog is not configured', 503, rid);

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const incoming = new URL(request.url);
    const query = new URLSearchParams();
    const q = incoming.searchParams.get('q')?.trim().slice(0, 200);
    if (q) query.set('q', q);
    const category = incoming.searchParams.get('category')?.trim();
    if (category && category.length <= 100) query.set('category', category);
    const categoryId = incoming.searchParams.get('category_id')?.trim();
    if (categoryId && categoryId.length <= 100) query.set('filter[category_id]', categoryId);
    const priceMin = incoming.searchParams.get('price_min');
    if (priceMin && /^\d+$/.test(priceMin)) query.set('filter[price_min]', priceMin);
    const priceMax = incoming.searchParams.get('price_max');
    if (priceMax && /^\d+$/.test(priceMax)) query.set('filter[price_max]', priceMax);
    const inStock = incoming.searchParams.get('in_stock');
    if (inStock === 'true' || inStock === 'false') query.set('filter[in_stock]', inStock);
    const page = Number(incoming.searchParams.get('page') ?? '1');
    if (Number.isInteger(page) && page >= 1 && page <= 10000) query.set('page', String(page));
    const limit = Number(incoming.searchParams.get('limit') ?? '20');
    if (Number.isInteger(limit) && limit >= 1 && limit <= 100) query.set('limit', String(limit));
    const sort = incoming.searchParams.get('sort');
    if (sort === 'popularity' || sort === 'price_asc' || sort === 'price_desc' || sort === 'new') query.set('sort', sort);
    const queryString = query.toString();
    const target = `${upstream.replace(/\/$/, '')}/api/v1/products${queryString ? `?${queryString}` : ''}`;
    const response = await fetch(target, {
      method: 'GET',
      headers: { Accept: 'application/json', 'X-Request-ID': rid },
      signal: controller.signal,
      cache: 'no-store',
    });
    const body = await response.text();
    return new NextResponse(body, {
      status: response.status,
      headers: { 'content-type': response.headers.get('content-type') ?? 'application/json', 'cache-control': 'no-store', 'X-Request-ID': rid },
    });
  } catch (error) {
    const timedOut = error instanceof DOMException && error.name === 'AbortError';
    return problem('https://neomarket.dev/problems/upstream-unavailable', timedOut ? 'Catalog timed out' : 'Catalog unavailable', 503, rid);
  } finally {
    clearTimeout(timeout);
  }
}
