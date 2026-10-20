import { NextResponse } from 'next/server';
import { requestId } from '@neomarket/telemetry';

export async function GET(request: Request, context: { params: Promise<{ attemptId: string }> }) {
  const rid = requestId(request.headers.get('x-request-id')); const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_access|nm_access)=([^;]+)/)?.[1]; const base = process.env.NEOMARKET_B2C_URL; const attemptId = (await context.params).attemptId;
  if (!token) return NextResponse.json({ type: 'about:blank', title: 'Buyer authentication is required', status: 401, requestId: rid }, { status: 401 });
  if (!base || !/^[0-9a-f-]{36}$/i.test(attemptId)) return NextResponse.json({ type: 'about:blank', title: 'Invalid checkout operation', status: 400, requestId: rid }, { status: 400 });
  const headers = { Accept: 'application/json', Authorization: `Bearer ${token}`, 'X-Request-ID': rid };
  const attempt = await fetch(`${base.replace(/\/$/, '')}/api/v1/checkout-attempts/${attemptId}`, { headers, cache: 'no-store' });
  if (attempt.ok) {
    const payload = await attempt.json() as { attempt_id?: string; status?: string; order_id?: string | null; updated_at?: string; created_at?: string; idempotency_key?: string; error_code?: string | null };
    const body = JSON.stringify({ ...payload, operation_id: payload.attempt_id, state: payload.status });
    return new NextResponse(body, { status: attempt.status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
  }
  // Legacy rows created before 0032 remain readable through the operation
  // endpoint while the attempt projection is being backfilled.
  const upstream = await fetch(`${base.replace(/\/$/, '')}/api/v1/checkout-operations/${attemptId}`, { headers, cache: 'no-store' });
  return new NextResponse(await upstream.text(), { status: upstream.status, headers: { 'Content-Type': upstream.headers.get('content-type') ?? 'application/json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
}
