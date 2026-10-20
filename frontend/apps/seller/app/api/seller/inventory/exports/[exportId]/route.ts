import { sellerProblem, sellerUpstreamFetch, sellerJsonResponse } from '../../../../../../src/lib/seller-problem-details';
import { NextResponse } from 'next/server';

const problem = (title: string, status: number) => sellerProblem(status, title, { cacheControl: 'private, no-store' });
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function GET(request: Request, context: { params: Promise<{ exportId: string }> }) {
  const { exportId } = await context.params;
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1];
  const base = process.env.NEOMARKET_B2B_URL;
  if (!uuid.test(exportId)) return problem('Inventory export was not found', 404);
  if (!token) return problem('Seller authentication is required', 401);
  if (!base) return problem('Seller service is not configured', 503);

  try {
    const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/api/v1/seller/inventory/exports/${exportId}`, {
      headers: { Accept: 'application/json', Authorization: `Bearer ${token}` },
      cache: 'no-store',
    });
    const body = await upstream.text();
    if (!upstream.ok) {
      return new NextResponse(body, {
        status: upstream.status,
        headers: { 'Content-Type': upstream.headers.get('content-type') ?? 'application/json', 'Cache-Control': 'private, no-store' },
      });
    }
    const result = JSON.parse(body) as { download_token?: unknown };
    const downloadToken = result.download_token;
    delete result.download_token;
    if (typeof downloadToken === 'string') {
      const query = new URLSearchParams({ token: downloadToken });
      Object.assign(result, { download_url: `/api/seller/inventory/exports/${exportId}/download?${query}` });
    }
    return sellerJsonResponse(request, result, { headers: { 'Cache-Control': 'private, no-store' } });
  } catch {
    return problem('Inventory export status is unavailable', 503);
  }
}
