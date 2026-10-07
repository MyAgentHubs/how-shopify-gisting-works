const MS_PER_SECOND = 1000;
const EXPIRY_PART = 1;
const PLAIN_SECONDS = /^[0-9]+$/;

export function ticketIfUsable(ticket: string | null, nowMs: number, marginMs: number): string | null {
  if (ticket === null) {
    return null;
  }
  const field = ticket.split(".")[EXPIRY_PART] ?? "";
  const expirySeconds = Number(field);
  if (!PLAIN_SECONDS.test(field) || !Number.isSafeInteger(expirySeconds) || expirySeconds <= 0) {
    return null;
  }
  return expirySeconds * MS_PER_SECOND - nowMs > marginMs ? ticket : null;
}
