import { isOidcReady } from '../../src/oidc';

export const dynamic = 'force-dynamic';

const messages: Record<string, string> = {
  invalid_response: 'Ответ входа не прошёл проверку. Начните вход заново.',
  authentication_failed: 'Keycloak не завершил вход. Попробуйте ещё раз.',
  mfa_required: 'Keycloak не подтвердил настроенный MFA claim. Вход отклонён.',
  access_unavailable: 'Учетная запись не активирована в NeoMarket Admin или сессия не создана.',
};

export default async function AdminLoginPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  const ready = isOidcReady();

  return <main className="private-shell admin-shell" id="admin-login-content" tabIndex={-1}><a className="skip-link" href="#admin-login-panel">Перейти к содержимому</a><div className="private-bar"><span>NEOMARKET / ADMIN</span><span>KEYCLOAK · OIDC + MFA</span></div><section className="private-panel admin-failsafe" id="admin-login-panel" tabIndex={-1}><p className="eyebrow">ADMIN / AD-01</p><h1>{ready ? 'Вход в консоль' : 'Вход закрыт'}</h1><p>{error ? messages[error] ?? 'Вход не выполнен. Начните заново.' : ready ? 'Продолжите через Keycloak. MFA проверяется на сервере до создания Admin-сессии.' : 'Keycloak или MFA claim mapping не настроен. Локальный вход недоступен; конфигурация должна включать issuer, confidential client и согласованный AMR или ACR claim.'}</p>{ready ? <a className="admin-action" href="/api/auth/login">Войти через Keycloak</a> : <span className="status-badge">ACCESS CLOSED</span>}</section></main>;
}
