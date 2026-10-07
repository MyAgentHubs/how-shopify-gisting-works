import { CounterCore } from "../counter-worker/src/counter-core";
import type { CounterHost, KvStore } from "../counter-worker/src/counter-core";
import type { CounterNamespace, CounterStub } from "../src/durable-counter";

export class FakeHost implements CounterHost {
  readonly store = new Map<string, unknown>();
  readonly sweeps: number[] = [];
  nowMs = 0;
  writes = 0;
  erased = 0;

  readonly kv: KvStore = {
    get: (key) => this.store.get(key),
    put: (key, value) => {
      this.writes += 1;
      this.store.set(key, value);
    },
  };

  now(): number {
    return this.nowMs;
  }

  scheduleSweep(atMs: number): Promise<void> {
    this.sweeps.push(atMs);
    return Promise.resolve();
  }

  erase(): Promise<void> {
    this.erased += 1;
    this.store.clear();
    return Promise.resolve();
  }
}

export class FakeObject {
  readonly host = new FakeHost();
  readonly core = new CounterCore(this.host);
}

const NETWORK_HOPS = 3;

async function hop(): Promise<void> {
  for (let index = 0; index < NETWORK_HOPS; index += 1) {
    await Promise.resolve();
  }
}

export class FakeNamespace implements CounterNamespace {
  readonly objects = new Map<string, FakeObject>();
  readonly requested: string[] = [];
  failure: unknown = null;
  gate: Promise<void> | null = null;
  reply: ((count: number) => unknown) | null = null;
  nowMs = 0;

  idFromName(name: string): string {
    this.requested.push(name);
    return name;
  }

  get(id: unknown): CounterStub {
    const name = String(id);
    const object = this.objects.get(name) ?? new FakeObject();
    this.objects.set(name, object);
    object.host.nowMs = this.nowMs;
    return {
      increment: async (ttlSeconds, limit) => {
        await hop();
        await this.gate;
        if (this.failure !== null) {
          // eslint-disable-next-line @typescript-eslint/only-throw-error
          throw this.failure;
        }
        const count = await object.core.increment(ttlSeconds, limit);
        await hop();
        return this.reply === null ? count : (this.reply(count) as number);
      },
    };
  }

  advance(ms: number): void {
    this.nowMs += ms;
  }

  async sweepAll(): Promise<void> {
    for (const object of this.objects.values()) {
      object.host.nowMs = this.nowMs;
      await object.core.sweep();
    }
  }
}
