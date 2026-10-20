import { ReportDetail } from '../../../src/ReportsQueue';

export default async function ReportDetailPage({ params }: { params: Promise<{ complaintId: string }> }) {
  const { complaintId } = await params;
  return <ReportDetail complaintId={complaintId} />;
}
