import { NextResponse } from 'next/server';
import { requestId } from '@neomarket/telemetry';

export async function GET(request: Request) {
  const rid = requestId(request.headers.get('x-request-id'));
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)(?:__Host-nm_access|nm_access)=([^;]+)/)?.[1];
  const key = request.headers.get('idempotency-key');
  const base = process.env.NEOMARKET_B2C_URL;
  if (!token) return NextResponse.json({ type: 'about:blank', title: 'Buyer authentication is required', status: 401, requestId: rid }, { status: 401 });
  if (!base || !key || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(key)) return NextResponse.json({ type: 'about:blank', title: 'A UUID Idempotency-Key is required', status: 400, requestId: rid }, { status: 400 });
  const upstream = await fetch(`${base.replace(/\/$/, '')}/api/v1/checkout-operations/by-idempotency`, { headers: { Accept: 'application/json', Authorization: `Bearer ${token}`, 'Idempotency-Key': key, 'X-Request-ID': rid }, cache: 'no-store' });
  return new NextResponse(await upstream.text(), { status: upstream.status, headers: { 'Content-Type': upstream.headers.get('content-type') ?? 'application/json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
}
