export type EvalCase = {
  readonly id: string;
  readonly red_line: 1 | 2 | 3 | 4 | "none";
  readonly category: string;
  readonly split: "train" | "dev" | "sealed";
  readonly family: string;
  readonly messages: readonly {
    readonly role: "user" | "assistant" | "tool";
    readonly content: string;
    readonly tool_calls: readonly {
      readonly name: string;
      readonly arguments: Readonly<Record<string, string>>;
    }[];
  }[];
  readonly fixtures: {
    readonly plan: string | null;
    readonly orders: readonly {
      readonly order: string;
      readonly email: "matching" | "wrong" | "absent";
    }[];
    readonly canary: {
      readonly allowed: readonly string[];
      readonly forbidden: readonly string[];
    };
  };
  readonly expect: {
    readonly turn: "first" | "second";
    readonly scenario: string | null;
    readonly order: string | null;
  };
};
