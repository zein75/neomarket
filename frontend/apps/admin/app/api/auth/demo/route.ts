import { NextRequest, NextResponse } from 'next/server';
import { publicOrigin, secureCookies } from '../../../../src/oidc';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function localDemoEnabled() {
  return (
    process.env.NODE_ENV === 'development' &&
    process.env.ADMIN_ALLOW_DEV_AUTH === 'true' &&
    process.env.NEOMARKET_DEMO_ADMIN_ENABLED === 'true' &&
    Boolean(process.env.NEOMARKET_DEMO_ADMIN_ACCESS) &&
    Boolean(process.env.NEOMARKET_DEMO_ADMIN_CSRF)
  );
}

export async function GET(request: NextRequest) {
  if (!localDemoEnabled()) {
    return NextResponse.json({ code: 'ADMIN_DEMO_DISABLED' }, { status: 404, headers: { 'Cache-Control': 'no-store' } });
  }

  try {
    const origin = publicOrigin();
    if (!['localhost', '127.0.0.1'].includes(request.nextUrl.hostname)) {
      return NextResponse.json({ code: 'ADMIN_DEMO_LOCAL_ORIGIN_REQUIRED' }, { status: 403, headers: { 'Cache-Control': 'no-store' } });
    }
    const returnTo = request.nextUrl.searchParams.get('returnTo') ?? '/dashboard';
    const target = returnTo.startsWith('/') && !returnTo.startsWith('//') ? returnTo : '/dashboard';
    const response = NextResponse.redirect(new URL(target, origin));
    const secure = secureCookies();
    response.cookies.set('nm_admin_access', process.env.NEOMARKET_DEMO_ADMIN_ACCESS!, {
      httpOnly: true,
      secure,
      sameSite: 'lax',
      path: '/',
      maxAge: 8 * 60 * 60,
    });
    response.cookies.set('nm_admin_csrf', process.env.NEOMARKET_DEMO_ADMIN_CSRF!, {
      httpOnly: false,
      secure,
      sameSite: 'strict',
      path: '/',
      maxAge: 8 * 60 * 60,
    });
    response.headers.set('Cache-Control', 'no-store');
    return response;
  } catch {
    return NextResponse.json({ code: 'ADMIN_DEMO_UNAVAILABLE' }, { status: 503, headers: { 'Cache-Control': 'no-store' } });
  }
}
