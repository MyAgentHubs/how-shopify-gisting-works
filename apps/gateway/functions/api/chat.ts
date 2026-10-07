import { handleChat } from "../../src/handler";
import type { Runtime } from "../../src/handler";
import { limits } from "../../src/limits";
import { gatewayEnv } from "../../src/pages-env";
import type { PagesEnv } from "../../src/pages-env";
import { replayTurns } from "../../src/replay";

function productionRuntime(): Runtime {
  return {
    limits,
    fetcher: (input, init) => fetch(input, init),
    logger: {
      record: (event) => {
        // eslint-disable-next-line no-console
        console.log(JSON.stringify(event));
      },
    },
    now: () => new Date(),
    replay: replayTurns,
  };
}

export const onRequestPost: PagesFunction<PagesEnv> = ({ request, env }) =>
  handleChat(request, gatewayEnv(env), productionRuntime());
