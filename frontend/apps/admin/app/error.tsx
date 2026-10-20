'use client';

export default function AdminError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <main className="private-shell admin-shell" id="admin-error-content" tabIndex={-1}><a className="skip-link" href="#admin-error-panel">Перейти к содержимому</a><div className="private-bar"><span>NEOMARKET / ADMIN</span><span>RECOVERABLE ERROR</span></div><section className="private-panel admin-failsafe" id="admin-error-panel" tabIndex={-1}><p className="eyebrow">ADMIN / ERROR</p><h1>Раздел недоступен</h1><p>Данные не подтверждены сервером. Повторите запрос или вернитесь назад.</p><button className="admin-action" type="button" onClick={() => reset()}>Повторить</button></section></main>;
}
