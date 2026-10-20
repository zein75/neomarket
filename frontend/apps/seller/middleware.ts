import { NextRequest, NextResponse } from 'next/server';

export async function middleware(request: NextRequest) {
  // Invitation acceptance is a public, one-use onboarding surface. The
  // client exchanges the fragment token for a password setup and then signs
  // the invitee in; it must remain reachable before a session exists.
  if (request.nextUrl.pathname === '/team/accept-invite') return NextResponse.next();

  // Local QA escape hatch only. Never enable this in staging/production.
  const devOpen = process.env.NODE_ENV === 'development' && process.env.NEOMARKET_DEV_OPEN_ACCESS === 'true';
  if (devOpen) return NextResponse.next();
  const hasSession = Boolean(request.cookies.get('__Host-nm_seller_access')?.value || request.cookies.get('nm_seller_access')?.value);
  if (hasSession) {
    // Cookie presence is not authentication. Revalidate the bearer with the
    // B2B auth/me contract before serving any private Seller route.
    try {
      const token = request.cookies.get('__Host-nm_seller_access')?.value || request.cookies.get('nm_seller_access')?.value;
      const internalB2B = process.env.NEOMARKET_B2B_URL?.replace(/\/$/, '');
      // Middleware runs inside the frontend container. Use the service DNS
      // name when configured; the public BFF origin is not resolvable from
      // that network in staging and would incorrectly turn valid sessions
      // into login redirects.
      const session = await fetch(
        internalB2B ? `${internalB2B}/auth/me` : new URL('/api/seller/auth/session', request.url),
        {
          headers: internalB2B
            ? { Accept: 'application/json', Authorization: `Bearer ${token}` }
            : { cookie: request.headers.get('cookie') ?? '' },
          cache: 'no-store',
        },
      );
      if (session.ok) return NextResponse.next();
    } catch {
      // Fail closed when the auth service is unavailable.
    }
    const rejected = NextResponse.redirect(new URL('/login', request.url));
    rejected.cookies.delete('__Host-nm_seller_access');
    rejected.cookies.delete('nm_seller_access');
    return rejected;
  }
  const login = new URL('/login', request.url); const target = `${request.nextUrl.pathname}${request.nextUrl.search}`;
  if (target.length <= 512) login.searchParams.set('next', target);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: [
    '/dashboard/:path*',
    '/products/:path*',
    '/inventory/:path*',
    '/imports/:path*',
    '/moderation/:path*',
    '/orders/:path*',
    '/team/:path*',
    '/finance/:path*',
    '/returns/:path*',
    '/settings/:path*',
    '/onboarding/:path*',
    '/analytics/:path*',
    '/support/:path*',
  ],
};
