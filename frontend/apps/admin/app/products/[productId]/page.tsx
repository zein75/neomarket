import { AdminRegistry } from '../../../src/AdminRegistries';
export const dynamic = 'force-dynamic'; export const revalidate = 0;
export default async function Page({ params }: { params: Promise<{ productId: string }> }) { const { productId } = await params; return <AdminRegistry kind="products" recordId={productId} />; }
