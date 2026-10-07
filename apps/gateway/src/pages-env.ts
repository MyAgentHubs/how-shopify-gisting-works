import type { GatewayEnv } from "./config";
import type { CounterNamespace } from "./durable-counter";
import { DurableCounter } from "./durable-counter";
import { limits } from "./limits";

export type PagesEnv = Omit<GatewayEnv, "GISTING_COUNTER"> & {
  readonly GISTING_COUNTER?: CounterNamespace;
};

export function gatewayEnv(env: PagesEnv): GatewayEnv {
  const { GISTING_COUNTER: namespace, ...rest } = env;
  return namespace === undefined ? rest : { ...rest, GISTING_COUNTER: new DurableCounter(namespace, limits.counterTimeoutMs) };
}
