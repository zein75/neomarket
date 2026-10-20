import type { MetadataRoute } from 'next';

export default function sitemap(): MetadataRoute.Sitemap {
  const base = process.env.NEOMARKET_PUBLIC_ORIGIN ?? 'https://www.example-market.test';
  return [
    { url: `${base}/`, changeFrequency: 'hourly', priority: 1 },
    { url: `${base}/catalog`, changeFrequency: 'hourly', priority: 0.9 },
    { url: `${base}/legal/terms`, changeFrequency: 'yearly', priority: 0.4 },
    { url: `${base}/legal/privacy`, changeFrequency: 'yearly', priority: 0.4 },
    { url: `${base}/legal/cookies`, changeFrequency: 'yearly', priority: 0.3 },
  ];
}
