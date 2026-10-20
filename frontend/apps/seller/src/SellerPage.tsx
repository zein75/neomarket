import { SellerSidebar } from './SellerSidebar';
export function SellerPage({ section, detail }: { section: string; detail: string }) {
  return <>
    <a className="skip-link" href="#main-content">К содержимому</a>
    <main className="seller-app" id="main-content"><SellerSidebar variant="blocked" activePath={`/${section}`} badge="VERIFICATION REQUIRED" /><section className="seller-content"><div className="private-bar"><span>SELLER / {section.toUpperCase()}</span><span>OWNER-SCOPED API</span></div><p className="eyebrow">SELLER HUB / {section.toUpperCase()}</p><h1>{section}</h1><div className="seller-blocked"><h2>Данные пока не подключены</h2><p>{detail}</p><span className="status-badge">API CONTRACT PENDING</span></div></section></main>
  </>;
}

