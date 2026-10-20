import { AdminRegistry } from '../../src/AdminRegistries';
export const dynamic = 'force-dynamic'; export const revalidate = 0;
export default function Page() { return <AdminRegistry kind="sellers" />; }
