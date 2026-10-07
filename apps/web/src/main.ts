import { boot } from "./boot.ts";
import { mountCalculator } from "./calculator.ts";
import { httpGateway } from "./gateway.ts";
import { browserHumanCheck } from "./turnstile.ts";

void boot({
  gateway: httpGateway((input, init) => fetch(input, init)),
  humanCheck: browserHumanCheck(document, window),
});
mountCalculator(document);
