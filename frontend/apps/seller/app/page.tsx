import { DevSellerPage } from '../src/DevSellerPage';

export default function SellerPage() {
  if (process.env.NODE_ENV === 'development' && process.env.NEOMARKET_DEV_OPEN_ACCESS === 'true') return <DevSellerPage />;
  return <main className="private-shell seller-shell"><div className="private-bar"><span>NEOMARKET / SELLER</span><span>PRIVATE · NOINDEX</span></div><section className="private-panel"><p className="eyebrow">SELLER / SE-03</p><h1>Seller Hub foundation</h1><p>Private seller shell готов. Данные появятся только после подключения server-side BFF и owner-scoped API.</p><span className="status-badge">API CONTRACT PENDING</span></section></main>;
}
