import { NextResponse } from 'next/server';

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const problem = (type: string, title: string, status: number, rid: string) => NextResponse.json({ type, title, status, requestId: rid }, { status, headers: { 'Content-Type': 'application/problem+json', 'X-Request-ID': rid, 'Cache-Control': 'no-store' } });

export async function GET(request: Request, context: { params: Promise<{ productId: string }> }) {
  const { productId } = await context.params;
  const rid = request.headers.get('x-request-id') ?? crypto.randomUUID();
  const base = process.env.NEOMARKET_B2C_URL;
  if (!uuid.test(productId)) return problem('https://neomarket.dev/problems/invalid-product-id', 'Invalid product id', 400, rid);
  if (!base) return problem('https://neomarket.dev/problems/product-not-configured', 'Product service is not configured', 503, rid);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2500);
  try {
    // Product detail uses the public canonical catalog contract. The
    // /products/{id} alias is intentionally hidden from the public schema.
    const response = await fetch(`${base.replace(/\/$/, '')}/api/v1/catalog/${productId}`, { headers: { Accept: 'application/json', 'x-request-id': rid }, cache: 'no-store', signal: controller.signal });
    const body = await response.text();
    return new NextResponse(body, { status: response.status, headers: { 'content-type': response.headers.get('content-type') ?? 'application/json', 'cache-control': 'no-store', 'X-Request-ID': rid } });
  } catch {
    return problem('https://neomarket.dev/problems/product-unavailable', 'Product service unavailable', 503, rid);
  } finally { clearTimeout(timeout); }
}
