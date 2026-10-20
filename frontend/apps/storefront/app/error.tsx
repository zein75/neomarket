'use client';

export default function ErrorPage({ reset }: { reset: () => void }) {
  return <main className="state-screen"><p className="eyebrow">[ 500 / RECOVERABLE ]</p><h1>Витрина временно недоступна</h1><p>Сохранили вашу корзину. Повторите запрос, когда сервис ответит.</p><button className="button button-primary" onClick={reset}>Повторить</button></main>;
}
