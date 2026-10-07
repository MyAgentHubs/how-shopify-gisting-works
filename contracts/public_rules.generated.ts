export type PublicRules = {
  readonly rules_file: string;
  readonly rules: string;
  readonly tools: readonly {
    readonly name: string;
    readonly description: string;
    readonly parameters: string;
  }[];
};
