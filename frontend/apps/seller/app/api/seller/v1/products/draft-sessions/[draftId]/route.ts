import { sellerProblem, sellerUpstreamFetch, sellerUpstreamResponse } from '../../../../../../../src/lib/seller-problem-details';
import { csrfMatches } from '../../../../../../../src/lib/csrf';
import { isTrustedSellerOrigin } from '../../../../../../../src/lib/trusted-origin';

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const problem = (title: string, status: number) => sellerProblem(status, title);

function accessToken(request: Request) {
  return request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1];
}

async function proxy(request: Request, draftId: string, method: 'GET' | 'PUT' | 'DELETE') {
  if (!isTrustedSellerOrigin(request)) return problem('Request origin is not trusted', 403);
  if (!uuid.test(draftId)) return problem('Invalid draft autosave key', 400);
  if (method !== 'GET' && !csrfMatches(request)) return problem('CSRF validation failed', 403);
  const token = accessToken(request);
  if (!token) return problem('Seller authentication is required', 401);
  const base = process.env.NEOMARKET_B2B_URL;
  if (!base) return problem('Seller service is not configured', 503);
  const headers = new Headers({ Accept: 'application/json', Authorization: `Bearer ${token}` });
  if (method === 'PUT') {
    headers.set('Content-Type', 'application/json');
    const ifMatch = request.headers.get('if-match');
    if (ifMatch) headers.set('If-Match', ifMatch);
  }
  try {
    const upstream = await sellerUpstreamFetch(request, `${base.replace(/\/$/, '')}/seller/v1/products/draft-sessions/${draftId}`, {
      method,
      headers,
      ...(method === 'PUT' ? { body: await request.text() } : {}),
      cache: 'no-store',
    });
    return await sellerUpstreamResponse(request, upstream);
  } catch {
    return problem('Seller draft autosave is unavailable', 503);
  }
}

export async function GET(request: Request, { params }: { params: Promise<{ draftId: string }> }) {
  return proxy(request, (await params).draftId, 'GET');
}

export async function PUT(request: Request, { params }: { params: Promise<{ draftId: string }> }) {
  return proxy(request, (await params).draftId, 'PUT');
}

export async function DELETE(request: Request, { params }: { params: Promise<{ draftId: string }> }) {
  return proxy(request, (await params).draftId, 'DELETE');
}
