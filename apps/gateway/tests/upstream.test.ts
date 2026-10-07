import { describe, expect, it } from "vitest";
import { limits } from "../src/limits";
import type { LogEvent } from "../src/types";
import type { Backend } from "../src/upstream";
import { forward } from "../src/upstream";
import { BACKUP, PRIMARY, bodyOf, healthyBackend, routedFetcher } from "./support";

const silent = { record: () => undefined };
const EVIL = "https://evil.example.test";

const primary: Backend = {
  name: "primary",
  baseUrl: PRIMARY,
  headers: {
    "cf-access-client-id": "id",
    "cf-access-client-secret": "secret",
    "x-gisting-upstream-secret": "upstream",
  },
  generateHeaders: { "x-gisting-ip-digest": "d".repeat(64) },
};
const backup: Backend = { name: "backup", baseUrl: BACKUP, headers: {}, generateHeaders: {} };
const payload = {
  sessionId: "session-0001",
  message: "hello",
  mode: "gist" as const,
};

function decode(chunk: ReadableStreamReadResult<Uint8Array>): string {
  const bytes: unknown = chunk.value;
  return bytes instanceof Uint8Array ? new TextDecoder().decode(bytes) : "";
}

describe("forward", () => {
  it("sends the generate request to the primary with the access headers", async () => {
    const { fetcher, calls } = routedFetcher(healthyBackend(PRIMARY, "answer"));
    const result = await forward(fetcher, [primary, backup], payload, limits, silent);
    expect(result.ok && (await result.value.text())).toBe("answer");
    const generate = calls.find((call) => call.url === `${PRIMARY}/generate`);
    expect(generate?.init?.headers).toMatchObject({
      "cf-access-client-id": "id",
    });
    expect(JSON.parse(generate === undefined ? "" : bodyOf(generate))).toEqual({
      session_id: "session-0001",
      message: "hello",
      mode: "gist",
    });
    expect(calls.some((call) => call.url.startsWith(BACKUP))).toBe(false);
  });

  it("sends the secret to the primary health and generate calls and the digest to generate only", async () => {
    const { fetcher, calls } = routedFetcher(healthyBackend(PRIMARY, "answer"));
    await forward(fetcher, [primary], payload, limits, silent);
    const health = new Headers(calls.find((call) => call.url === `${PRIMARY}/health`)?.init?.headers);
    const generate = new Headers(calls.find((call) => call.url === `${PRIMARY}/generate`)?.init?.headers);
    expect(health.get("x-gisting-upstream-secret")).toBe("upstream");
    expect(generate.get("x-gisting-upstream-secret")).toBe("upstream");
    expect(health.has("x-gisting-ip-digest")).toBe(false);
    expect(generate.get("x-gisting-ip-digest")).toBe("d".repeat(64));
  });

  it("labels the answer with the backend that served it and keeps the content type", async () => {
    const { fetcher } = routedFetcher(healthyBackend(PRIMARY, "answer"));
    const result = await forward(fetcher, [primary], payload, limits, silent);
    expect(result.ok && result.value.headers.get("x-served-by")).toBe("primary");
    expect(result.ok && result.value.headers.get("content-type")).toBe("text/plain");
  });

  it("switches to the backup when the primary health check fails, without access headers", async () => {
    const { fetcher, calls } = routedFetcher({
      [`${PRIMARY}/health`]: () => new Response("down", { status: 503 }),
      ...healthyBackend(BACKUP, "from backup"),
    });
    const result = await forward(fetcher, [primary, backup], payload, limits, silent);
    expect(result.ok && result.value.headers.get("x-served-by")).toBe("backup");
    expect(result.ok && (await result.value.text())).toBe("from backup");
    expect(calls.some((call) => call.url === `${PRIMARY}/generate`)).toBe(false);
    const secretsSentToBackup = calls
      .filter((call) => call.url.startsWith(BACKUP))
      .some((call) => JSON.stringify(call.init?.headers).includes("secret"));
    expect(secretsSentToBackup).toBe(false);
  });

  it("switches to the backup when the primary is healthy but generate fails", async () => {
    const { fetcher } = routedFetcher({
      [`${PRIMARY}/health`]: () => new Response("ok"),
      [`${PRIMARY}/generate`]: () => new Response("boom", { status: 500 }),
      ...healthyBackend(BACKUP, "from backup"),
    });
    const result = await forward(fetcher, [primary, backup], payload, limits, silent);
    expect(result.ok && result.value.headers.get("x-served-by")).toBe("backup");
  });

  it("switches to the backup when the primary is unreachable", async () => {
    const { fetcher } = routedFetcher(healthyBackend(BACKUP, "from backup"));
    const result = await forward(fetcher, [primary, backup], payload, limits, silent);
    expect(result.ok && result.value.headers.get("x-served-by")).toBe("backup");
  });

  it("reports an upstream error naming each failed attempt when nothing answers", async () => {
    const { fetcher } = routedFetcher({});
    const result = await forward(fetcher, [primary, backup], payload, limits, silent);
    expect(result).toEqual({
      ok: false,
      error: {
        kind: "UpstreamError",
        attempts: ["primary:unhealthy", "backup:unhealthy"],
      },
    });
  });

  it("reports an upstream error when no backup is configured", async () => {
    const { fetcher } = routedFetcher({});
    const result = await forward(fetcher, [primary], payload, limits, silent);
    expect(result).toMatchObject({
      ok: false,
      error: { kind: "UpstreamError" },
    });
  });

  it("passes chunks through as they arrive instead of buffering the whole answer", async () => {
    const encoder = new TextEncoder();
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const stream = new ReadableStream<Uint8Array>({
      async start(controller) {
        controller.enqueue(encoder.encode("first "));
        await gate;
        controller.enqueue(encoder.encode("second"));
        controller.close();
      },
    });
    const { fetcher } = routedFetcher({
      [`${PRIMARY}/health`]: () => new Response("ok"),
      [`${PRIMARY}/generate`]: () => new Response(stream),
    });
    const result = await forward(fetcher, [primary], payload, limits, silent);
    if (!result.ok || result.value.body === null) {
      throw new Error("expected a streamed response");
    }
    const reader = result.value.body.getReader();
    expect(decode(await reader.read())).toBe("first ");
    release();
    expect(decode(await reader.read())).toBe("second");
    expect((await reader.read()).done).toBe(true);
  });

  it.each(["/health", "/generate"])("never follows a redirect from the primary %s", async (path) => {
    const { fetcher, calls } = routedFetcher({
      [`${PRIMARY}/health`]: () => new Response("ok"),
      [`${PRIMARY}${path}`]: () => new Response(null, { status: 302, headers: { location: EVIL } }),
      ...healthyBackend(BACKUP, "from backup"),
    });
    const result = await forward(fetcher, [primary, backup], payload, limits, silent);
    expect(result.ok && result.value.headers.get("x-served-by")).toBe("backup");
    expect(calls.some((call) => call.url.startsWith(EVIL))).toBe(false);
    for (const call of calls) {
      expect(call.init?.redirect).toBe("manual");
    }
  });

  it.each(["/health", "/generate"])("records an unauthorized primary %s apart from an unhealthy one", async (path) => {
    const { fetcher } = routedFetcher({
      [`${PRIMARY}/health`]: () => new Response("ok"),
      [`${PRIMARY}${path}`]: () => new Response("no", { status: 401 }),
      ...healthyBackend(BACKUP, "from backup"),
    });
    const events: LogEvent[] = [];
    const result = await forward(fetcher, [primary, backup], payload, limits, {
      record: (event) => events.push(event),
    });
    expect(result.ok && result.value.headers.get("x-served-by")).toBe("backup");
    expect(events).toEqual([{ kind: "UpstreamError", detail: "primary:unauthorized:401" }]);
  });

  it("still fails with an upstream error when an unauthorized primary has no backup", async () => {
    const { fetcher } = routedFetcher({ [`${PRIMARY}/health`]: () => new Response("no", { status: 401 }) });
    const events: LogEvent[] = [];
    const result = await forward(fetcher, [primary], payload, limits, { record: (event) => events.push(event) });
    expect(result).toMatchObject({ ok: false, error: { kind: "UpstreamError", attempts: ["primary:unhealthy"] } });
    expect(events).toHaveLength(1);
  });

  it.each([403, 500, 503])("does not call a primary answering %i unauthorized", async (status) => {
    const { fetcher } = routedFetcher({ [`${PRIMARY}/health`]: () => new Response("x", { status }) });
    const events: LogEvent[] = [];
    await forward(fetcher, [primary], payload, limits, { record: (event) => events.push(event) });
    expect(events).toEqual([]);
  });
});
