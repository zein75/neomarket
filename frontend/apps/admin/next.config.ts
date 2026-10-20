import type { NextConfig } from 'next';

const csp = [
  "default-src 'self'",
  "base-uri 'self'",
  "object-src 'none'",
  "frame-ancestors 'none'",
  "form-action 'self'",
  "img-src 'self' data: https://images.unsplash.com",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  `script-src 'self' 'unsafe-inline'${process.env.NODE_ENV === 'production' ? '' : " 'unsafe-eval'"}`,
  "connect-src 'self' https://fonts.googleapis.com https://fonts.gstatic.com",
  "font-src 'self' data: https://fonts.gstatic.com",
].join('; ');

const nextConfig: NextConfig = {
  output: 'standalone',
  transpilePackages: ['@neomarket/ui'],
  async headers() {
    return [{ source: '/(.*)', headers: [
      { key: 'Content-Security-Policy', value: csp },
      { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
      { key: 'X-Content-Type-Options', value: 'nosniff' },
      { key: 'X-Frame-Options', value: 'DENY' },
      { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=(), payment=()' },
    ] }];
  },
};

export default nextConfig;
