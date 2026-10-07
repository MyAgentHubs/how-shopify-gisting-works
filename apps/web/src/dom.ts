export type Child = Node | string;

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Readonly<Record<string, string>> = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    node.setAttribute(name, value);
  }
  node.append(...children);
  return node;
}

export function role<T extends HTMLElement>(
  root: ParentNode,
  name: string,
  type: abstract new () => T,
): T {
  const node = root.querySelector(`[data-role="${name}"]`);
  if (!(node instanceof type)) {
    throw new ReferenceError(`page needs data-role="${name}" to be a ${type.name}`);
  }
  return node;
}
