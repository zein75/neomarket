'use client';

export default function SellerError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <main className="private-shell seller-shell"><div className="private-bar"><span>NEOMARKET / SELLER</span><span>RECOVERABLE ERROR</span></div><section className="private-panel seller-failsafe"><p className="eyebrow">SELLER / ERROR</p><h1>Не удалось загрузить раздел</h1><p>Сервер не подтвердил данные. Повторите запрос; технические детали не показываются в браузере.</p><div className="failsafe-actions"><button className="seller-submit" type="button" onClick={() => reset()}>Повторить</button><a className="seller-product-link" href="/dashboard">В dashboard</a></div></section></main>;
}
