import type { Limits } from "./limits";
import type { Fetcher, GatewayError, Logger, Result } from "./types";
import { fail, ok } from "./types";

const HEALTH_PATH = "/health";
const GENERATE_PATH = "/generate";
const SERVED_BY_HEADER = "x-served-by";
const UNAUTHORIZED = 401;

export interface Backend {
  readonly name: "primary" | "backup";
  readonly baseUrl: string;
  readonly headers: Readonly<Record<string, string>>;
  readonly generateHeaders: Readonly<Record<string, string>>;
}

export interface GeneratePayload {
  readonly sessionId: string;
  readonly message: string;
  readonly mode: "gist" | "full";
}

function noteUnauthorized(response: Response, backend: Backend, logger: Logger): void {
  if (response.status === UNAUTHORIZED) {
    logger.record({ kind: "UpstreamError", detail: `${backend.name}:unauthorized:${String(UNAUTHORIZED)}` });
  }
}

async function isHealthy(
  fetcher: Fetcher,
  backend: Backend,
  timeoutMs: number,
  logger: Logger,
): Promise<boolean> {
  try {
    const response = await fetcher(backend.baseUrl + HEALTH_PATH, {
      headers: backend.headers,
      redirect: "manual",
      signal: AbortSignal.timeout(timeoutMs),
    });
    noteUnauthorized(response, backend, logger);
    await response.body?.cancel();
    return response.ok;
  } catch {
    return false;
  }
}

type GenerateFailure = "generate failed" | "generate timeout";

function failureOf(thrown: unknown): GenerateFailure {
  return thrown instanceof Error && thrown.name === "TimeoutError" ? "generate timeout" : "generate failed";
}

async function generate(
  fetcher: Fetcher,
  backend: Backend,
  payload: GeneratePayload,
  timeoutMs: number,
  logger: Logger,
): Promise<Response | GenerateFailure> {
  try {
    const response = await fetcher(backend.baseUrl + GENERATE_PATH, {
      method: "POST",
      headers: { ...backend.headers, ...backend.generateHeaders, "content-type": "application/json" },
      redirect: "manual",
      signal: AbortSignal.timeout(timeoutMs),
      body: JSON.stringify({
        session_id: payload.sessionId,
        message: payload.message,
        mode: payload.mode,
      }),
    });
    noteUnauthorized(response, backend, logger);
    if (response.ok && response.body !== null) {
      return response;
    }
    await response.body?.cancel();
    return "generate failed";
  } catch (thrown) {
    return failureOf(thrown);
  }
}

function passThrough(upstream: Response, backend: Backend): Response {
  const headers = new Headers({ [SERVED_BY_HEADER]: backend.name });
  const contentType = upstream.headers.get("content-type");
  if (contentType !== null) {
    headers.set("content-type", contentType);
  }
  return new Response(upstream.body, { status: 200, headers });
}

export async function forward(
  fetcher: Fetcher,
  backends: readonly Backend[],
  payload: GeneratePayload,
  limits: Limits,
  logger: Logger,
): Promise<Result<Response, GatewayError>> {
  const attempts: string[] = [];
  for (const backend of backends) {
    if (!(await isHealthy(fetcher, backend, limits.healthTimeoutMs, logger))) {
      attempts.push(`${backend.name}:unhealthy`);
      continue;
    }
    const upstream = await generate(fetcher, backend, payload, limits.generateTimeoutMs, logger);
    if (upstream instanceof Response) {
      return ok(passThrough(upstream, backend));
    }
    attempts.push(`${backend.name}:${upstream}`);
  }
  return fail({ kind: "UpstreamError", attempts });
}
