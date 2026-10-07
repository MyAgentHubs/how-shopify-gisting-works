export interface BuiltPages {
  readonly outDir: string;
  readonly html: (lang: string) => string;
  readonly css: () => string;
  readonly doc: (lang: string) => Document;
}

export function buildPages(change?: (webDir: string) => void): BuiltPages;
