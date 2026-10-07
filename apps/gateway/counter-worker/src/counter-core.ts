const WINDOW_KEY = "window";
const MS_PER_SECOND = 1000;

export interface KvStore {
  get(key: string): unknown;
  put(key: string, value: unknown): void;
}

export interface CounterHost {
  readonly kv: KvStore;
  now(): number;
  scheduleSweep(atMs: number): Promise<void>;
  erase(): Promise<void>;
}

interface Window {
  readonly count: number;
  readonly expiresAt: number;
}

function isWindow(value: unknown): value is Window {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const { count, expiresAt } = value as Record<string, unknown>;
  return (
    typeof count === "number" &&
    Number.isInteger(count) &&
    count >= 1 &&
    typeof expiresAt === "number" &&
    Number.isFinite(expiresAt) &&
    expiresAt > 0
  );
}

function assertWindowSeconds(ttlSeconds: number): void {
  if (!Number.isInteger(ttlSeconds) || ttlSeconds < 1) {
    throw new RangeError("window length must be a positive whole number of seconds");
  }
}

function assertLimit(limit: number): void {
  if (!Number.isInteger(limit) || limit < 1) {
    throw new RangeError("limit must be a positive whole number");
  }
}

export class CounterCore {
  private readonly host: CounterHost;

  constructor(host: CounterHost) {
    this.host = host;
  }

  async increment(ttlSeconds: number, limit: number): Promise<number> {
    assertWindowSeconds(ttlSeconds);
    assertLimit(limit);
    const now = this.host.now();
    const live = this.live(now);
    if ((live?.count ?? 0) >= limit) {
      return limit + 1;
    }
    const next: Window = {
      count: (live?.count ?? 0) + 1,
      expiresAt: live?.expiresAt ?? now + ttlSeconds * MS_PER_SECOND,
    };
    this.host.kv.put(WINDOW_KEY, next);
    if (live === undefined) {
      await this.host.scheduleSweep(next.expiresAt);
    }
    return next.count;
  }

  async sweep(): Promise<void> {
    const live = this.live(this.host.now());
    if (live === undefined) {
      await this.host.erase();
      return;
    }
    await this.host.scheduleSweep(live.expiresAt);
  }

  private live(now: number): Window | undefined {
    const stored = this.host.kv.get(WINDOW_KEY);
    if (stored === undefined) {
      return undefined;
    }
    if (!isWindow(stored)) {
      throw new TypeError("stored counter state is not recognised");
    }
    return stored.expiresAt > now ? stored : undefined;
  }
}
