export type PublicTrace = {
  readonly tools: readonly {
    readonly tool: string;
    readonly order_number: string | null;
    readonly outcome: "completed" | "unavailable" | "locked";
  }[];
  readonly knowledge: readonly {
    readonly id: string;
    readonly method: "bm25";
  }[];
  readonly tokens: {
    readonly rules: number;
    readonly tools: number;
    readonly history: number;
    readonly tool_results: number;
    readonly total: number;
  };
  readonly latency: {
    readonly first_token_ms: number;
    readonly total_ms: number;
  };
};
