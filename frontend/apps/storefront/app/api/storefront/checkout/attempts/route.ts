import { NextResponse } from 'next/server';
import { requestId } from '@neomarket/telemetry';

function problem(type: string, title: string, status: number, rid: string) {
  return NextResponse.json({ type, title, status, requestId: rid }, { status, headers: { 'Content-Type': 'application/problem+json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
}
function trustedMutation(request: Request) {
  const origin = request.headers.get('origin');
  const expected = process.env.NEOMARKET_PUBLIC_ORIGIN?.replace(/\/$/, '');
  const localOrigin = new URL(request.url).origin;
  const configuredOrigin = Boolean(origin && expected && origin === expected);
  const sameOriginDevelopment = process.env.NODE_ENV !== 'production' && origin === localOrigin;
  return (!origin || configuredOrigin || sameOriginDevelopment) && request.headers.get('sec-fetch-site') !== 'cross-site';
}
function cookie(request: Request, name: string) { return request.headers.get('cookie')?.match(new RegExp(`(?:^|;\\s*)${name}=([^;]+)`))?.[1]; }

export async function POST(request: Request) {
  const rid = requestId(request.headers.get('x-request-id'));
  if (!trustedMutation(request)) return problem('https://neomarket.dev/problems/csrf-origin', 'Request origin is not trusted', 403, rid);
  const csrf = cookie(request, 'nm_csrf');
  if (!csrf || request.headers.get('x-csrf-token') !== csrf) return problem('https://neomarket.dev/problems/csrf', 'CSRF validation failed', 403, rid);
  const access = cookie(request, process.env.NODE_ENV === 'production' ? '__Host-nm_access' : 'nm_access') ?? cookie(request, '__Host-nm_access') ?? cookie(request, 'nm_access');
  if (!access) return problem('https://neomarket.dev/problems/auth-required', 'Buyer authentication is required for checkout', 401, rid);
  const key = request.headers.get('idempotency-key');
  if (!key || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(key)) return problem('https://neomarket.dev/problems/idempotency-key', 'A UUID Idempotency-Key is required', 400, rid);
  const base = process.env.NEOMARKET_B2C_URL;
  if (!base) return problem('https://neomarket.dev/problems/checkout-not-configured', 'Checkout service is not configured', 503, rid);
  const payload = await request.json().catch(() => null) as { cartId?: unknown; addressId?: unknown; deliveryMethod?: unknown; paymentMethodId?: unknown; comment?: unknown; contact?: unknown; legalConsents?: unknown; quoteId?: unknown } | null;
  if (!payload || typeof payload.addressId !== 'string' || !/^[0-9a-f-]{36}$/i.test(payload.addressId) || typeof payload.deliveryMethod !== 'string' || payload.deliveryMethod.length > 64) return problem('https://neomarket.dev/problems/checkout-request', 'A saved address and delivery method are required', 400, rid);
  // Checkout is a durable saga (cart validation, B2B reservation and order
  // commit).  A ten-second proxy deadline could abort the browser request
  // after B2C had already committed the order, surfacing a false
  // "unknown" result and forcing an unnecessary retry. Keep the BFF budget
  // below the browser test/request ceiling while allowing the reservation
  // saga to finish and return its idempotent result.
  const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 25000);
  try {
    const legalConsents = Array.isArray(payload.legalConsents)
      ? payload.legalConsents.flatMap((consent) => {
          if (!consent || typeof consent !== 'object') return [];
          const item = consent as { type?: unknown; version?: unknown; acceptedAt?: unknown; accepted_at?: unknown };
          if (typeof item.type !== 'string' || typeof item.version !== 'string') return [];
          const acceptedAt = typeof item.accepted_at === 'string' ? item.accepted_at : item.acceptedAt;
          return typeof acceptedAt === 'string' ? [{ type: item.type, version: item.version, accepted_at: acceptedAt }] : [];
        })
      : undefined;
    const upstream = await fetch(`${base.replace(/\/$/, '')}/api/v1/orders`, { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json', Authorization: `Bearer ${access}`, 'Idempotency-Key': key, 'X-Request-ID': rid }, body: JSON.stringify({ ...(typeof payload.cartId === 'string' ? { cart_id: payload.cartId } : {}), address_id: payload.addressId, delivery_method: payload.deliveryMethod, ...(typeof payload.paymentMethodId === 'string' ? { payment_method_id: payload.paymentMethodId } : {}), ...(typeof payload.comment === 'string' ? { comment: payload.comment } : {}), ...(payload.contact && typeof payload.contact === 'object' ? { contact: payload.contact } : {}), ...(legalConsents ? { legal_consents: legalConsents } : {}), ...(typeof payload.quoteId === 'string' ? { quote_id: payload.quoteId } : {}) }), cache: 'no-store', signal: controller.signal });
    const body = await upstream.text();
    const headers = { 'Content-Type': upstream.headers.get('content-type') ?? 'application/json', 'Cache-Control': 'no-store', 'X-Request-ID': rid, ...(upstream.headers.get('location') ? { Location: upstream.headers.get('location')! } : {}) };
    return new NextResponse(body, { status: upstream.status, headers });
  } catch (error) { return problem('https://neomarket.dev/problems/checkout-unavailable', error instanceof DOMException && error.name === 'AbortError' ? 'Checkout timed out; retry with the same Idempotency-Key' : 'Checkout unavailable', 503, rid); }
  finally { clearTimeout(timeout); }
}
