// @vitest-environment happy-dom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vite-plus/test";
import { ThemeToggle } from "../components/theme-toggle";
import { initTheme, useDarkTheme } from "./use-theme";

it("applies and persists theme choices while following system changes", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const media = Object.assign(new EventTarget(), { matches: false });
  vi.stubGlobal("matchMedia", () => media);
  const unsubscribe = vi.spyOn(media, "removeEventListener");
  localStorage.setItem("protein-detective-theme", "dark");
  initTheme();
  function Preview() {
    const dark = useDarkTheme();
    return createElement("output", null, dark ? "dark" : "light");
  }
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  const choose = (title: string) =>
    act(async () => container.querySelector<HTMLButtonElement>(`[title="${title}"]`)!.click());
  try {
    await act(async () => {
      root.render(createElement("div", null, createElement(ThemeToggle), createElement(Preview)));
    });
    expect(container.querySelector("output")?.textContent).toBe("dark");
    expect(container.querySelector('[title="Dark"]')?.getAttribute("aria-pressed")).toBe("true");

    await choose("Light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(localStorage.getItem("protein-detective-theme")).toBe("light");
    expect(container.querySelector("output")?.textContent).toBe("light");

    await act(async () => {
      media.matches = true;
      media.dispatchEvent(new Event("change"));
    });
    expect(container.querySelector("output")?.textContent).toBe("light");

    await choose("System");
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(localStorage.getItem("protein-detective-theme")).toBe("system");
    expect(container.querySelector("output")?.textContent).toBe("dark");

    await act(async () => {
      media.matches = false;
      media.dispatchEvent(new Event("change"));
    });
    expect(container.querySelector("output")?.textContent).toBe("light");
  } finally {
    await act(async () => root.unmount());
    container.remove();
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    vi.unstubAllGlobals();
  }
  expect(unsubscribe).toHaveBeenCalledWith("change", expect.any(Function));
});
