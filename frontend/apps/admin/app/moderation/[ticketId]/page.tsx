import { ModerationTicket } from '../../../src/ModerationTicket';

export default async function ModerationTicketPage({ params }: { params: Promise<{ ticketId: string }> }) {
  const { ticketId } = await params;
  return <ModerationTicket ticketId={ticketId} />;
}
