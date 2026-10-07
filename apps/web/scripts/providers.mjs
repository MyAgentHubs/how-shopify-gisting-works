import { savingsProvider } from "../src/savings-provider.ts";
import { examplesProvider } from "./examples.mjs";
import { publicOrdersProvider } from "./public-orders.mjs";
import { rulesProvider } from "./rules.mjs";

function requireSum(label, total, parts) {
  const sum = parts.reduce((left, right) => left + right, 0);
  if (sum !== total) {
    throw new RangeError(`composition: ${label} is ${total} but its parts add up to ${sum}`);
  }
}

function composition({ numbers }) {
  const { rulesFull, rulesGist, toolsTokens, chatTokens, fullCall, gistCall, savedPerCall } = numbers;
  requireSum("full call", fullCall, [rulesFull, toolsTokens, chatTokens]);
  requireSum("gist call", gistCall, [rulesGist, toolsTokens, chatTokens]);
  requireSum("fixed rules before and after", rulesFull, [rulesGist, savedPerCall]);
  return {};
}

function linksProvider({ links }) {
  if (links === null) {
    throw new TypeError("the links provider needs the link file");
  }
  return links;
}

export const DEFAULT_PROVIDERS = {
  composition,
  savings: savingsProvider,
  examples: examplesProvider,
  publicOrders: publicOrdersProvider,
  site: ({ assetsBase }) => ({ assetsBase }),
  rules: rulesProvider,
  links: linksProvider,
};
