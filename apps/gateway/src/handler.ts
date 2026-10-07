import type { Config, GatewayEnv } from "./config";
import { loadConfig } from "./config";
import { clientIp, digestIp } from "./ip";
import type { Limits } from "./limits";
import { enforceQuota } from "./quota";
import type { ReplayReason, ReplayTurn } from "./replay";
import { replayResponse } from "./replay";
import { describeError, errorResponse, withTicket } from "./respond";
import type { Fetcher, GatewayError, Logger, Result } from "./types";
import { fail, ok } from "./types";
import type { TicketSubject } from "./ticket";
import { issueTicket, verifyTicket } from "./ticket";
import { verifyTurnstile } from "./turnstile";
import type { Backend } from "./upstream";
import { forward } from "./upstream";
import type { ChatRequest } from "./validate";
import { parseChatRequest } from "./validate";

const HTTP_OK = 200;

export interface Runtime {
  readonly limits: Limits;
  readonly fetcher: Fetcher;
  readonly logger: Logger;
  readonly now: () => Date;
  readonly replay: readonly ReplayTurn[];
}

function backends(config: Config, ipDigest: string): Backend[] {
  const primary: Backend = {
    name: "primary",
    baseUrl: config.primaryUrl,
    headers: {
      "cf-access-client-id": config.accessClientId,
      "cf-access-client-secret": config.accessClientSecret,
      "x-gisting-upstream-secret": config.upstreamSecret,
    },
    generateHeaders: { "x-gisting-ip-digest": ipDigest },
  };
  const backup: Backend[] =
    config.backupUrl === null ? [] : [{ name: "backup", baseUrl: config.backupUrl, headers: {}, generateHeaders: {} }];
  return [primary, ...backup];
}

interface Caller {
  readonly ip: string;
  readonly digest: string;
}

async function identify(
  request: Request,
  config: Config,
  now: Date,
): Promise<Result<Caller, GatewayError>> {
  const ip = clientIp(request);
  if (!ip.ok) {
    return ip;
  }
  return ok({ ip: ip.value, digest: await digestIp(config.ipSalt, ip.value, now) });
}

function subjectOf(chat: ChatRequest, caller: Caller): TicketSubject {
  return { sessionId: chat.sessionId, ip: caller.ip };
}

async function checkHuman(
  chat: ChatRequest,
  config: Config,
  runtime: Runtime,
  caller: Caller,
): Promise<Result<{ readonly fresh: boolean }, GatewayError>> {
  if (chat.ticket !== null) {
    const { limits } = runtime;
    const window = { ttlSeconds: limits.ticketTtlSeconds, skewSeconds: limits.ticketClockSkewSeconds };
    const held = await verifyTicket(config.ipSalt, chat.ticket, subjectOf(chat, caller), runtime.now(), window);
    if (held.ok) {
      return ok({ fresh: false });
    }
    if (chat.turnstileToken === null) {
      return held;
    }
    runtime.logger.record({ kind: held.error.kind, detail: describeError(held.error) });
  }
  if (chat.turnstileToken === null) {
    return fail({ kind: "InvalidRequest", reason: "missing field" });
  }
  const human = await verifyTurnstile(
    runtime.fetcher,
    config.turnstileSecret,
    chat.turnstileToken,
    runtime.limits.turnstileTimeoutMs,
    config.turnstilePolicy,
  );
  return human.ok ? ok({ fresh: true }) : human;
}

interface Intake {
  readonly config: Config;
  readonly chat: ChatRequest;
  readonly caller: Caller;
}

async function intake(
  request: Request,
  env: GatewayEnv,
  runtime: Runtime,
): Promise<Result<Intake, GatewayError>> {
  const config = loadConfig(env);
  if (!config.ok) {
    return config;
  }
  const chat = await parseChatRequest(request, runtime.limits);
  if (!chat.ok) {
    return chat;
  }
  const caller = await identify(request, config.value, runtime.now());
  return caller.ok ? ok({ config: config.value, chat: chat.value, caller: caller.value }) : caller;
}

interface Served {
  readonly outcome: Result<Response, GatewayError>;
  readonly ticket: string | null;
}

async function serve(request: Request, env: GatewayEnv, runtime: Runtime): Promise<Served> {
  const received = await intake(request, env, runtime);
  if (!received.ok) {
    return { outcome: received, ticket: null };
  }
  const { config, chat, caller } = received.value;
  const human = await checkHuman(chat, config, runtime, caller);
  if (!human.ok) {
    return { outcome: human, ticket: null };
  }
  const { limits } = runtime;
  const ticket = human.value.fresh
    ? await issueTicket(config.ipSalt, subjectOf(chat, caller), runtime.now(), limits.ticketTtlSeconds)
    : null;
  const quota = await enforceQuota(config.counter, limits, {
    ipDigest: caller.digest,
    sessionId: chat.sessionId,
    mode: chat.mode,
    now: runtime.now(),
  });
  if (!quota.ok) {
    return { outcome: quota, ticket };
  }
  return { outcome: await forward(runtime.fetcher, backends(config, caller.digest), chat, limits, runtime.logger), ticket };
}

function replayReason(error: GatewayError): ReplayReason | null {
  switch (error.kind) {
    case "CounterUnavailable":
    case "UpstreamError":
      return "offline";
    case "QuotaExceeded":
      return error.scope === "site" ? "quota" : null;
    case "TurnstileFailed":
    case "TooLong":
    case "InvalidRequest":
    case "ConfigMissing":
      return null;
  }
}

function rejected(error: GatewayError, runtime: Runtime): Response {
  runtime.logger.record({ kind: error.kind, detail: describeError(error) });
  const reason = replayReason(error);
  return reason === null ? errorResponse(error) : replayResponse(runtime.replay, reason);
}

export async function handleChat(
  request: Request,
  env: GatewayEnv,
  runtime: Runtime,
): Promise<Response> {
  const { outcome, ticket } = await serve(request, env, runtime);
  const response = outcome.ok ? outcome.value : rejected(outcome.error, runtime);
  return ticket !== null && response.status === HTTP_OK ? withTicket(response, ticket) : response;
}
