import { AccountDashboard } from '../../src/AccountDashboard';

export const metadata = { title: 'Аккаунт', robots: { index: false, follow: false } };

export default function AccountPage() {
  return <AccountDashboard />;
}
