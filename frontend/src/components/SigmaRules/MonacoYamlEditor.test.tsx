import { render, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

// S-154 Task 7: airgap support — MonacoYamlEditor must call
// `loader.config({ monaco })` at module load so `@monaco-editor/react`
// uses the locally-bundled monaco instance instead of fetching from a
// jsdelivr CDN. We mock both `@monaco-editor/react` (to capture the
// loader.config call) and `monaco-editor` (so the test does not pull in
// the real ~3 MB module under jsdom).
//
// `vi.mock` is hoisted to the top of the file, so the spy reference must
// be created via `vi.hoisted` to be accessible inside the mock factory.
const { loaderConfigSpy } = vi.hoisted(() => ({ loaderConfigSpy: vi.fn() }));

vi.mock("@monaco-editor/react", () => ({
  default: () => null,
  loader: { config: loaderConfigSpy },
}));

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
