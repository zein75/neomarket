import { AuthForm } from '../../src/AuthForm';
export const metadata = { title: 'Вход', robots: { index: false, follow: false } };
export default function LoginPage() { return <AuthForm mode="login" />; }
