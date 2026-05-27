import { render, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { SEERFLOW_MONACO_THEME } from "./monacoTheme";

// S-154 Task 7: airgap support — MonacoYamlEditor must call
// `loader.config({ monaco })` at module load so `@monaco-editor/react`
// uses the locally-bundled monaco instance instead of fetching from a
// jsdelivr CDN.
//
// S-327 (AC1): on mount the editor must register and activate the Seerflow
// brand theme — `monaco.editor.defineTheme(SEERFLOW_MONACO_THEME, ...)` via
// `beforeMount` and `monaco.editor.setTheme(SEERFLOW_MONACO_THEME)` via
// `onMount`. The mocked `Editor` drives those lifecycle callbacks with a
// fake `monaco` whose `editor.defineTheme` / `editor.setTheme` are spies so
// we assert the wiring without rendering the real ~3 MB Monaco bundle.
//
// `vi.mock` is hoisted to the top of the file, so the spy references must be
// created via `vi.hoisted` to be accessible inside the mock factory.
const { loaderConfigSpy, defineThemeSpy, setThemeSpy, editorPropsSpy } =
  vi.hoisted(() => ({
    loaderConfigSpy: vi.fn(),
    defineThemeSpy: vi.fn(),
    setThemeSpy: vi.fn(),
    editorPropsSpy: vi.fn(),
  }));

vi.mock("@monaco-editor/react", () => {
  const fakeMonaco = {
    __isMockedMonaco: true,
    editor: { defineTheme: defineThemeSpy, setTheme: setThemeSpy },
  };
  return {
    default: (props: Record<string, unknown>) => {
      editorPropsSpy(props);
      const beforeMount = props.beforeMount as
        | ((m: typeof fakeMonaco) => void)
        | undefined;
      const onMount = props.onMount as
        | ((e: unknown, m: typeof fakeMonaco) => void)
        | undefined;
      beforeMount?.(fakeMonaco);
      onMount?.({ __fakeEditor: true }, fakeMonaco);
      return null;
    },
    loader: { config: loaderConfigSpy },
  };
});

vi.mock("monaco-editor", () => ({
  __isMockedMonaco: true,
}));

import { MonacoYamlEditor } from "./MonacoYamlEditor";

describe("MonacoYamlEditor (airgap config)", () => {
  it("configures @monaco-editor/react with the locally-bundled monaco instance", async () => {
    render(<MonacoYamlEditor value="" onChange={() => {}} />);

    await waitFor(() => expect(loaderConfigSpy).toHaveBeenCalledTimes(1));

    const arg = loaderConfigSpy.mock.calls[0]?.[0] as { monaco: unknown };
    expect(arg.monaco).toBeDefined();
    expect((arg.monaco as { __isMockedMonaco?: boolean }).__isMockedMonaco).toBe(
      true,
    );
  });
});

describe("MonacoYamlEditor (S-327 brand theming)", () => {
  beforeEach(() => {
    defineThemeSpy.mockClear();
    setThemeSpy.mockClear();
    editorPropsSpy.mockClear();
  });

  it("registers the Seerflow theme via defineTheme before mount", async () => {
    render(<MonacoYamlEditor value="" onChange={() => {}} />);

    await waitFor(() => expect(defineThemeSpy).toHaveBeenCalled());

    const [themeName, themeData] = defineThemeSpy.mock.calls[0] as [
      string,
      { base?: string },
    ];
    expect(themeName).toBe(SEERFLOW_MONACO_THEME);
    expect(themeData).toBeTypeOf("object");
    expect(themeData.base).toBe("vs-dark");
  });

  it("activates the Seerflow theme via setTheme on mount", async () => {
    render(<MonacoYamlEditor value="" onChange={() => {}} />);

    await waitFor(() => expect(setThemeSpy).toHaveBeenCalled());
    expect(setThemeSpy).toHaveBeenCalledWith(SEERFLOW_MONACO_THEME);
  });

  it("passes the Seerflow theme name as the editor `theme` prop", async () => {
    render(<MonacoYamlEditor value="" onChange={() => {}} />);

    await waitFor(() => expect(editorPropsSpy).toHaveBeenCalled());
    const props = editorPropsSpy.mock.calls.at(-1)?.[0] as { theme?: string };
    expect(props.theme).toBe(SEERFLOW_MONACO_THEME);
  });
});
