import { NextResponse } from 'next/server';
import { requestId } from '@neomarket/telemetry';

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const problem = (title: string, status: number, rid: string) => NextResponse.json({ type: 'about:blank', title, status, requestId: rid }, { status, headers: { 'Content-Type': 'application/problem+json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } });

export async function POST(request: Request) {
  const rid = requestId(request.headers.get('x-request-id')); const expected = process.env.NEOMARKET_PUBLIC_ORIGIN?.replace(/\/$/, ''); const origin = request.headers.get('origin');
  if ((origin && (!expected || origin !== expected)) || request.headers.get('sec-fetch-site') === 'cross-site') return problem('Request origin is not trusted', 403, rid);
  const base = process.env.NEOMARKET_B2C_URL; if (!base) return problem('Banner events are not configured', 503, rid);
  const payload = await request.json().catch(() => null) as { events?: unknown } | null;
  const events = Array.isArray(payload?.events) ? payload.events.slice(0, 20).filter((item): item is { banner_id: string; event: 'impression' | 'click' } => Boolean(item && typeof item === 'object' && typeof (item as { banner_id?: unknown }).banner_id === 'string' && uuid.test((item as { banner_id: string }).banner_id) && ((item as { event?: unknown }).event === 'impression' || (item as { event?: unknown }).event === 'click'))) : [];
  if (!events.length) return problem('At least one valid banner event is required', 400, rid);
  try {
    const upstream = await fetch(`${base.replace(/\/$/, '')}/api/v1/banner-events`, { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Request-ID': rid }, body: JSON.stringify({ events }), cache: 'no-store' });
    return new NextResponse(await upstream.text(), { status: upstream.status, headers: { 'Content-Type': upstream.headers.get('content-type') ?? 'application/json', 'Cache-Control': 'no-store', 'X-Request-ID': rid } });
  } catch { return problem('Banner events are unavailable', 503, rid); }
}
