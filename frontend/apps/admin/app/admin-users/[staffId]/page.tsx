import { StaffProfile } from '../../../src/AdminUsers';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export default async function Page({ params }: { params: Promise<{ staffId: string }> }) { const { staffId } = await params; return <StaffProfile staffId={staffId} />; }
