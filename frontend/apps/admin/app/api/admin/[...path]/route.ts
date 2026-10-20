import type { NextRequest } from 'next/server';
import { NextResponse } from 'next/server';
import { apiUrl, publicOrigin, secureCookies } from '../../../../src/oidc';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const revalidate = 0;

type Context = { params: Promise<{ path: string[] }> };

const forwardedHeaders = ['accept', 'content-type', 'if-match', 'if-none-match', 'idempotency-key', 'range', 'x-request-id'];

async function proxy(request: NextRequest, context: Context) {
  try {
    const { path } = await context.params;
    if (!path.length || path.some((part) => !part || part === '.' || part === '..' || /[\\/\0]/.test(part))) {
      return NextResponse.json({ code: 'INVALID_ADMIN_PATH' }, { status: 400, headers: { 'Cache-Control': 'no-store' } });
    }

    const productionCookies = secureCookies();
    const accessName = productionCookies ? '__Host-nm_admin_access' : 'nm_admin_access';
    const csrfName = productionCookies ? '__Host-nm_admin_csrf' : 'nm_admin_csrf';
    const access = request.cookies.get(accessName)?.value;
    const csrf = request.cookies.get(csrfName)?.value;
    if (!access || !csrf) return NextResponse.json({ code: 'ADMIN_SESSION_REQUIRED' }, { status: 401, headers: { 'Cache-Control': 'no-store' } });
    const origin = publicOrigin();
    const mutating = !['GET', 'HEAD', 'OPTIONS'].includes(request.method);
    if (mutating && (request.headers.get('Origin') !== origin || request.headers.get('Sec-Fetch-Site') === 'cross-site')) {
      return NextResponse.json({ code: 'CSRF_VALIDATION_FAILED' }, { status: 403, headers: { 'Cache-Control': 'no-store' } });
    }

    const headers = new Headers();
    for (const name of forwardedHeaders) {
      const value = request.headers.get(name);
      if (value) headers.set(name, value);
    }
    headers.set('Cookie', `${accessName}=${encodeURIComponent(access)}; ${csrfName}=${encodeURIComponent(csrf)}`);
    headers.set('Origin', origin);
    headers.set('Sec-Fetch-Site', 'same-origin');
    if (mutating) headers.set('X-CSRF-Token', csrf);

    const url = new URL(apiUrl(`/admin/${path.map(encodeURIComponent).join('/')}`));
    url.search = request.nextUrl.search;
    const init: RequestInit = {
      method: request.method,
      headers,
      cache: 'no-store',
      redirect: 'manual',
    };
    if (!['GET', 'HEAD'].includes(request.method)) init.body = await request.arrayBuffer();
    const upstream = await fetch(url, init);
    const responseHeaders = new Headers({ 'Cache-Control': 'private, no-store' });
    for (const name of ['content-type', 'content-disposition', 'x-content-sha256', 'etag', 'retry-after', 'x-request-id']) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    if (path.join('/') === 'v1/session/logout') {
      for (const cookie of upstream.headers.getSetCookie()) responseHeaders.append('Set-Cookie', cookie);
    }
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch {
    return NextResponse.json({ code: 'ADMIN_UPSTREAM_UNAVAILABLE' }, { status: 502, headers: { 'Cache-Control': 'no-store' } });
  }
}

export const GET = proxy;
export const HEAD = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
