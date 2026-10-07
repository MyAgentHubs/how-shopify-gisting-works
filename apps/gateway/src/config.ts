import type { Counter, GatewayError, Result } from "./types";
import { limits } from "./limits";
import { fail, ok } from "./types";
import type { TurnstilePolicy } from "./turnstile-policy";
import { extraHostnames, turnstilePolicy } from "./turnstile-policy";

export interface GatewayEnv {
  readonly GISTING_TURNSTILE_SECRET?: string;
  readonly GISTING_IP_SALT?: string;
  readonly GISTING_PRIMARY_URL?: string;
  readonly GISTING_BACKUP_URL?: string;
  readonly GISTING_ACCESS_CLIENT_ID?: string;
  readonly GISTING_ACCESS_CLIENT_SECRET?: string;
  readonly GISTING_UPSTREAM_SECRET?: string;
  readonly GISTING_COUNTER?: Counter;
  readonly GISTING_TURNSTILE_EXTRA_HOSTNAMES?: unknown;
}

export interface Config {
  readonly turnstileSecret: string;
  readonly ipSalt: string;
  readonly primaryUrl: string;
  readonly backupUrl: string | null;
  readonly accessClientId: string;
  readonly accessClientSecret: string;
  readonly upstreamSecret: string;
  readonly counter: Counter;
  readonly turnstilePolicy: TurnstilePolicy;
}

function present(value: string | undefined): value is string {
  return value !== undefined && value.trim() !== "";
}

function strong(value: string | undefined): boolean {
  return present(value) && value.length >= limits.minSecretChars;
}

function isHttps(value: string): boolean {
  try {
    return new URL(value).protocol === "https:";
  } catch {
    return false;
  }
}

function usableUrl(value: string | undefined): boolean {
  return present(value) && isHttps(value);
}

function missingNames(env: GatewayEnv, extra: readonly string[] | null): string[] {
  const required: [string, boolean][] = [
    ["GISTING_TURNSTILE_SECRET", present(env.GISTING_TURNSTILE_SECRET)],
    ["GISTING_IP_SALT", strong(env.GISTING_IP_SALT)],
    ["GISTING_PRIMARY_URL", usableUrl(env.GISTING_PRIMARY_URL)],
    ["GISTING_ACCESS_CLIENT_ID", present(env.GISTING_ACCESS_CLIENT_ID)],
    ["GISTING_ACCESS_CLIENT_SECRET", present(env.GISTING_ACCESS_CLIENT_SECRET)],
    ["GISTING_UPSTREAM_SECRET", present(env.GISTING_UPSTREAM_SECRET)],
    ["GISTING_COUNTER", env.GISTING_COUNTER !== undefined],
    ["GISTING_BACKUP_URL", !present(env.GISTING_BACKUP_URL) || usableUrl(env.GISTING_BACKUP_URL)],
    ["GISTING_TURNSTILE_EXTRA_HOSTNAMES", extra !== null],
  ];
  return required.filter(([, isSet]) => !isSet).map(([name]) => name);
}

function text(value: string | undefined): string {
  return value ?? "";
}

export function loadConfig(env: GatewayEnv): Result<Config, GatewayError> {
  const extra = extraHostnames(env.GISTING_TURNSTILE_EXTRA_HOSTNAMES);
  const missing = missingNames(env, extra);
  const counter = env.GISTING_COUNTER;
  if (missing.length > 0 || counter === undefined || extra === null) {
    return fail({ kind: "ConfigMissing", missing });
  }
  return ok({
    turnstileSecret: text(env.GISTING_TURNSTILE_SECRET),
    ipSalt: text(env.GISTING_IP_SALT),
    primaryUrl: text(env.GISTING_PRIMARY_URL),
    backupUrl: present(env.GISTING_BACKUP_URL) ? env.GISTING_BACKUP_URL : null,
    accessClientId: text(env.GISTING_ACCESS_CLIENT_ID),
    accessClientSecret: text(env.GISTING_ACCESS_CLIENT_SECRET),
    upstreamSecret: text(env.GISTING_UPSTREAM_SECRET),
    counter,
    turnstilePolicy: turnstilePolicy(extra),
  });
}
