import { AdminRegistry } from '../../../src/AdminRegistries';
export const dynamic = 'force-dynamic'; export const revalidate = 0;
export default async function Page({ params }: { params: Promise<{ sellerId: string }> }) { const { sellerId } = await params; return <AdminRegistry kind="sellers" recordId={sellerId} />; }
