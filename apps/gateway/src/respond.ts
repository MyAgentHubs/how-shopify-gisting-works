import type { GatewayError } from "./types";

const STATUS_BY_KIND: Readonly<Record<GatewayError["kind"], number>> = {
  InvalidRequest: 400,
  TurnstileFailed: 403,
  TooLong: 413,
  QuotaExceeded: 429,
  UpstreamError: 502,
  CounterUnavailable: 503,
  ConfigMissing: 503,
};

const TICKET_HEADER = "x-gisting-ticket";

export function withTicket(response: Response, ticket: string): Response {
  const headers = new Headers(response.headers);
  headers.set(TICKET_HEADER, ticket);
  return new Response(response.body, { status: response.status, headers });
}

export function errorResponse(error: GatewayError): Response {
  return new Response(JSON.stringify({ error: "request_failed" }), {
    status: STATUS_BY_KIND[error.kind],
    headers: { "content-type": "application/json" },
  });
}

export function describeError(error: GatewayError): string {
  switch (error.kind) {
    case "TurnstileFailed":
      return error.detail === undefined ? error.reason : `${error.reason}:${error.detail}`;
    case "QuotaExceeded":
      return error.scope;
    case "TooLong":
      return `max ${String(error.max)}`;
    case "InvalidRequest":
      return error.reason;
    case "UpstreamError":
      return error.attempts.join(", ");
    case "ConfigMissing":
      return error.missing.join(", ");
    case "CounterUnavailable":
      return [
        "counter unavailable",
        ...(error.reason === undefined ? [] : [error.reason]),
        ...(error.causeName === undefined ? [] : [`cause ${error.causeName}`]),
      ].join(": ");
  }
}
