import type { MetadataRoute } from 'next';

export default function robots(): MetadataRoute.Robots {
  const base = process.env.NEOMARKET_PUBLIC_ORIGIN ?? 'https://www.example-market.test';
  return { rules: { userAgent: '*', allow: ['/', '/catalog', '/product/', '/catalog/category/'], disallow: ['/account', '/cart', '/checkout', '/checkout/status', '/favorites', '/login', '/register', '/reset-password', '/maintenance', '/bff', '/api'] }, sitemap: `${base}/sitemap.xml` };
}
