import replayData from "../replay.json";

export interface ReplayTurn {
  readonly role: "user" | "assistant";
  readonly content: string;
}

interface ReplayFile {
  readonly status: string;
  readonly turns: readonly ReplayTurn[];
}

const file = replayData as ReplayFile;

export const replayTurns: readonly ReplayTurn[] = file.turns;

export type ReplayReason = "quota" | "offline";

export function replayResponse(turns: readonly ReplayTurn[], reason: ReplayReason): Response {
  return new Response(JSON.stringify({ served_by: "replay", reason, turns }), {
    status: 200,
    headers: { "content-type": "application/json", "x-served-by": "replay" },
  });
}
