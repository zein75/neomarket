import { sellerCommercialFlowDisabledResponse, sellerProblem } from '../../../../../../src/lib/seller-problem-details';
import { csrfMatches } from '../../../../../../src/lib/csrf';
import { isTrustedSellerOrigin } from '../../../../../../src/lib/trusted-origin';

const problem = (title: string, status: number) => sellerProblem(status, title);
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function POST(request: Request, context: { params: Promise<{ orderId: string }> }) {
  if (!isTrustedSellerOrigin(request)) return problem('Request origin is not trusted', 403);
  if (!csrfMatches(request)) return problem('CSRF validation failed', 403);
  const { orderId } = await context.params;
  const idempotencyKey = request.headers.get('Idempotency-Key');
  if (!uuid.test(orderId)) return problem('Invalid allocation id', 400);
  if (!idempotencyKey || !uuid.test(idempotencyKey)) return problem('A valid Idempotency-Key is required', 400);
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_seller_access|nm_seller_access)=([^;]+)/)?.[1];
  if (!token) return problem('Seller authentication is required', 401);
  return sellerCommercialFlowDisabledResponse(request, 'seller_packing_manifest');
}
