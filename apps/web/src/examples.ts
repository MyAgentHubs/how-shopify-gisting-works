const PREFILL_BUTTONS = "[data-prefill]";
const FILLED_CLASS = "og-filled";

export function bindExamples(
  root: ParentNode,
  input: HTMLInputElement,
  onUse: () => void,
  flashMs: number,
): void {
  let flash: ReturnType<typeof setTimeout> | undefined;
  for (const button of root.querySelectorAll<HTMLButtonElement>(PREFILL_BUTTONS)) {
    button.addEventListener("click", () => {
      if (input.disabled) {
        return;
      }
      onUse();
      input.value = button.dataset["prefill"] ?? "";
      input.focus();
      clearTimeout(flash);
      input.classList.add(FILLED_CLASS);
      flash = setTimeout(() => {
        input.classList.remove(FILLED_CLASS);
      }, flashMs);
    });
  }
}
