export type Benchmarks = {
  readonly source: {
    readonly code_tree_sha: string;
    readonly rules_version: string;
    readonly backend_id: string;
    readonly splits: readonly string[];
    readonly graded: number;
  };
  readonly tokens: {
    readonly full: {
      readonly turns: number;
      readonly model_calls: number;
      readonly rules_tokens_per_call: number;
      readonly prefill_tokens_per_turn: number;
      readonly total_tokens_per_turn: number;
    };
    readonly gist: {
      readonly turns: number;
      readonly model_calls: number;
      readonly rules_tokens_per_call: number;
      readonly prefill_tokens_per_turn: number;
      readonly total_tokens_per_turn: number;
    };
  };
  readonly composition: {
    readonly tools_tokens_per_call: number;
    readonly chat_tokens_per_call: number;
    readonly calls_per_case: number;
    readonly saved_per_call: number;
    readonly saved_per_turn: number;
    readonly prefix_tokens: number;
    readonly full_call_tokens: number;
    readonly gist_call_tokens: number;
  };
  readonly red_lines: readonly {
    readonly metric: string;
    readonly min_cases: number;
    readonly results: {
      readonly full: {
        readonly raw: {
          readonly failures: number;
          readonly n: number;
          readonly rate: number;
          readonly upper95: number;
        };
        readonly final: {
          readonly failures: number;
          readonly n: number;
          readonly rate: number;
          readonly upper95: number;
        };
      };
      readonly gist: {
        readonly raw: {
          readonly failures: number;
          readonly n: number;
          readonly rate: number;
          readonly upper95: number;
        };
        readonly final: {
          readonly failures: number;
          readonly n: number;
          readonly rate: number;
          readonly upper95: number;
        };
      };
    };
  }[];
};
