import { AppealDetail } from '../../../src/AppealsQueue';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export default async function Page({ params }: { params: Promise<{ appealId: string }> }) { const { appealId } = await params; return <AppealDetail appealId={appealId} />; }
