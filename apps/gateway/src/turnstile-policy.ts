import policyData from "../turnstile.json";

export interface TurnstilePolicy {
  readonly action: string;
  readonly hostnames: ReadonlySet<string>;
}

const LABEL = "[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?";
const HOSTNAME = new RegExp(`^${LABEL}(?:\\.${LABEL})*$`);

export function extraHostnames(raw: unknown): readonly string[] | null {
  if (raw === undefined) {
    return [];
  }
  if (typeof raw !== "string") {
    return null;
  }
  const names = raw
    .split(",")
    .map((name) => name.trim())
    .filter((name) => name !== "");
  return names.every((name) => HOSTNAME.test(name)) ? names.map((name) => name.toLowerCase()) : null;
}

export function turnstilePolicy(extra: readonly string[]): TurnstilePolicy {
  return { action: policyData.action, hostnames: new Set([...policyData.hostnames, ...extra]) };
}
