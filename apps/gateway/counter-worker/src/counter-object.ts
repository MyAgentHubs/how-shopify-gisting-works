import { DurableObject } from "cloudflare:workers";
import { CounterCore } from "./counter-core";

export class CounterObject extends DurableObject {
  private readonly core: CounterCore;

  constructor(ctx: DurableObjectState, env: Cloudflare.Env) {
    super(ctx, env);
    this.core = new CounterCore({
      kv: ctx.storage.kv,
      now: () => Date.now(),
      scheduleSweep: (atMs) => ctx.storage.setAlarm(atMs),
      erase: () => ctx.storage.deleteAll(),
    });
  }

  increment(ttlSeconds: number, limit: number): Promise<number> {
    return this.core.increment(ttlSeconds, limit);
  }

  override alarm(): Promise<void> {
    return this.core.sweep();
  }
}
