export type Pricing = {
  readonly source: string;
  readonly accessed: string;
  readonly default: string;
  readonly models: readonly {
    readonly id: string;
    readonly name: string;
    readonly short: string;
    readonly input: number;
    readonly cache_read: number;
    readonly min_cacheable: number;
  }[];
  readonly calculator: {
    readonly days_per_month: number;
    readonly default_per_day: number;
    readonly default_turns: number;
    readonly max_turns: number;
    readonly stops: readonly number[];
    readonly chart_stops: readonly number[];
  };
};
