export function LegalPage({ kind }: { kind: 'privacy' | 'terms' | 'cookies' }) {
  const content = {
    privacy: ['Конфиденциальность', 'Здесь будет опубликована утверждённая политика обработки персональных данных. Не добавляем юридические обещания до sign-off.'],
    terms: ['Условия использования', 'Здесь будут опубликованы утверждённые условия использования NeoMarket и правила работы с заказами.'],
    cookies: ['Cookies', 'Здесь будет опубликована утверждённая политика cookies и список необходимых consent-категорий.'],
  }[kind];
  return <main className="content-section legal-page"><p className="eyebrow">LEGAL / {kind.toUpperCase()}</p><h1>{content[0]}</h1><div className="legal-notice"><strong>Текст ожидает утверждения legal</strong><p>{content[1]}</p></div><a className="button button-secondary" href="/catalog">Вернуться в каталог</a></main>;
}
