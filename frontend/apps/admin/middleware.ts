import { NextRequest, NextResponse } from 'next/server';

export async function middleware(request: NextRequest) {
  const pathname = request.nextUrl.pathname;
  if (
    pathname === '/login' ||
    pathname === '/unauthorized' ||
    pathname === '/api/health' ||
    pathname === '/api/auth/login' ||
    pathname === '/api/auth/callback' ||
    pathname === '/api/auth/demo'
  ) {
    return NextResponse.next();
  }

  // Keep API consumers on a machine-readable boundary; page redirects turn
  // auth failures into misleading HTML responses inside fetch().
  if (pathname.startsWith('/api/admin/')) {
    const hasSession = Boolean(request.cookies.get('__Host-nm_admin_access')?.value || request.cookies.get('nm_admin_access')?.value);
    if (!hasSession) return NextResponse.json({ code: 'ADMIN_SESSION_REQUIRED' }, { status: 401, headers: { 'Cache-Control': 'no-store' } });

    // Reject cross-origin mutations before consulting the session service. A
    // forged or expired cookie must not change the response for a CSRF attempt
    // into an authentication result; the BFF owns this boundary and the
    // upstream API still validates the session and CSRF token independently.
    const mutating = !['GET', 'HEAD', 'OPTIONS'].includes(request.method);
    if (mutating) {
      const configuredOrigin = process.env.NEOMARKET_PUBLIC_ORIGIN?.trim();
      const expectedOrigin = configuredOrigin || request.nextUrl.origin;
      if (request.headers.get('Origin') !== expectedOrigin || request.headers.get('Sec-Fetch-Site') === 'cross-site') {
        return NextResponse.json({ code: 'CSRF_VALIDATION_FAILED' }, { status: 403, headers: { 'Cache-Control': 'no-store' } });
      }
    }
  }

  // Local QA escape hatch only. Never enable this in staging/production.
  const devOpen = process.env.NODE_ENV === 'development' && process.env.NEOMARKET_DEV_OPEN_ACCESS === 'true';
  if (devOpen) return NextResponse.next();
  const hasSession = Boolean(request.cookies.get('__Host-nm_admin_access')?.value || request.cookies.get('nm_admin_access')?.value);
  if (hasSession) {
    // Cookie presence is never sufficient for privileged access. The OIDC/MFA
    // session service must validate the cookie and return an admin principal.
    const sessionService = process.env.NEOMARKET_ADMIN_SESSION_SERVICE_URL;
    if (sessionService) {
      try {
        const session = await fetch(`${sessionService.replace(/\/$/, '')}/session`, {
          headers: { Accept: 'application/json', cookie: request.headers.get('cookie') ?? '' },
          cache: 'no-store',
        });
        const payload = await session.json().catch(() => null) as { authenticated?: unknown; principal?: { role?: unknown } } | null;
        if (session.ok && payload?.authenticated === true && payload.principal?.role === 'admin') return NextResponse.next();
      } catch {
        // Fail closed when the identity provider/session service is unavailable.
      }
    }
    if (pathname.startsWith('/api/admin/')) {
      const rejected = NextResponse.json({ code: 'ADMIN_SESSION_INVALID' }, { status: 401, headers: { 'Cache-Control': 'no-store' } });
      rejected.cookies.delete('__Host-nm_admin_access');
      rejected.cookies.delete('nm_admin_access');
      return rejected;
    }
    const rejected = NextResponse.redirect(new URL('/unauthorized', request.url));
    rejected.cookies.delete('__Host-nm_admin_access');
    rejected.cookies.delete('nm_admin_access');
    return rejected;
  }
  return NextResponse.redirect(new URL('/unauthorized', request.url));
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico|robots.txt).*)'],
};
