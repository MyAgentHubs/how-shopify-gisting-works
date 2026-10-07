const ISO_DATE_LENGTH = 10;

export function utcDay(now: Date): string {
  return now.toISOString().slice(0, ISO_DATE_LENGTH);
}
