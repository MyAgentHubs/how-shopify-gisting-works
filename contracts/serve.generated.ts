export type ServeContract = {
  readonly request: {
    readonly session_id: string;
    readonly message: string;
    readonly mode: "gist" | "full";
  };
  readonly response: {
    readonly answer: string;
    readonly trace: {
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
  };
  readonly error: {
    readonly error: {
      readonly type: "busy" | "timeout" | "not_ready" | "invalid_request" | "too_long" | "compare_unavailable" | "unauthorized" | "internal";
      readonly retry_after_s?: number;
    };
  };
  readonly health: {
    readonly status: "ready" | "loading";
    readonly running: number;
    readonly waiting: number;
  };
};
