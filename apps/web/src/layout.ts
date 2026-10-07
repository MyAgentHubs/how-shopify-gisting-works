export const NARROW_QUERY = "(max-width: 820px)";

type MatchMedia = (query: string) => MediaQueryList;

export function collapseWhenNarrow(hood: HTMLDetailsElement, matchMedia: MatchMedia): void {
  if (matchMedia(NARROW_QUERY).matches) {
    hood.open = false;
  }
}
