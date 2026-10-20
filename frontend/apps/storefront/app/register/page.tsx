import { AuthForm } from '../../src/AuthForm';
export const metadata = { title: 'Регистрация', robots: { index: false, follow: false } };
export default function RegisterPage() { return <AuthForm mode="register" />; }
