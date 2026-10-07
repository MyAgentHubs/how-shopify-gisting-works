import type { Counter } from "./types";
import { CounterFailure } from "./types";

const KEY_GRAMMAR = /^(session|full|ip|site)(:[A-Za-z0-9_-]+)+$/;
const MAX_KEY_LENGTH = 160;

export interface CounterStub {
  increment(ttlSeconds: number, limit: number): Promise<number>;
}

export interface CounterNamespace {
  idFromName(name: string): unknown;
  get(id: unknown): CounterStub;
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1;
}

function within<T>(work: () => Promise<T>, timeoutMs: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new CounterFailure("durable_object_timeout"));
    }, timeoutMs);
    work().then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (cause: unknown) => {
        clearTimeout(timer);
        reject(new CounterFailure("durable_object_unreachable", { cause }));
      },
    );
  });
}

export class DurableCounter implements Counter {
  private readonly namespace: CounterNamespace;
  private readonly timeoutMs: number;

  constructor(namespace: CounterNamespace, timeoutMs: number) {
    this.namespace = namespace;
    this.timeoutMs = timeoutMs;
  }

  async increment(key: string, ttlSeconds: number, limit: number): Promise<number> {
    if (key.length > MAX_KEY_LENGTH || !KEY_GRAMMAR.test(key)) {
      throw new CounterFailure("counter_key_rejected");
    }
    const reply: unknown = await within(
      async () => this.namespace.get(this.namespace.idFromName(key)).increment(ttlSeconds, limit),
      this.timeoutMs,
    );
    if (!isCount(reply)) {
      throw new CounterFailure("durable_object_bad_reply");
    }
    return reply;
  }
}
