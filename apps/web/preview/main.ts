import { boot } from "../src/boot.ts";
import { mountCalculator } from "../src/calculator.ts";
import { fakeGateway } from "../fakes/fake-gateway.ts";
import type { Gateway } from "../src/gateway.ts";

const PREVIEW_TOKEN = "preview";
const PREVIEW_REPLY_DELAY_MS = 2000;
const fake = fakeGateway();
const gateway: Gateway = {
  async chat(request) {
    await new Promise<void>((resolve) => setTimeout(resolve, PREVIEW_REPLY_DELAY_MS));
    return fake.chat(request);
  },
};

void boot({
  gateway,
  humanCheck: () => ({ warm: () => undefined, reset: () => undefined, token: () => Promise.resolve(PREVIEW_TOKEN) }),
});
mountCalculator(document);
