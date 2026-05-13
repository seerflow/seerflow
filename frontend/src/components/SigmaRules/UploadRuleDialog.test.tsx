import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { UploadRuleDialog } from "./UploadRuleDialog";
import * as sigmaApi from "@/lib/sigmaRulesApi";

vi.mock("./MonacoYamlEditor", () => ({
  MonacoYamlEditor: ({ value, onChange }: { value: string; onChange?: (v: string) => void }) => (
    <textarea
      data-testid="yaml-editor"
      value={value}
      onChange={(e) => onChange?.(e.target.value)}
    />
  ),
}));

vi.mock("@/lib/sigmaRulesApi", () => ({
  validateSigmaRule: vi.fn(),
  uploadSigmaRule: vi.fn(),
}));

const mockedValidate = sigmaApi.validateSigmaRule as unknown as ReturnType<typeof vi.fn>;
const mockedUpload = sigmaApi.uploadSigmaRule as unknown as ReturnType<typeof vi.fn>;

describe("UploadRuleDialog", () => {
  it("save is disabled until validate succeeds", async () => {
    render(<UploadRuleDialog open onClose={() => {}} onSaved={() => {}} />);
    fireEvent.change(screen.getByTestId("yaml-editor"), {
      target: { value: "title: T" },
    });
    expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();

    mockedValidate.mockResolvedValueOnce({ valid: true, rule_id: "rid", title: "T" });
    fireEvent.click(screen.getByRole("button", { name: /validate/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /save/i })).not.toBeDisabled(),
    );
    await waitFor(() => expect(screen.getByTestId("sigma-upload-result")).toBeInTheDocument());
    expect(screen.getByTestId("sigma-upload-result").textContent).toMatch(/valid/i);
  });

  it("invalid validation surfaces stage + line", async () => {
    render(<UploadRuleDialog open onClose={() => {}} onSaved={() => {}} />);
    fireEvent.change(screen.getByTestId("yaml-editor"), {
      target: { value: "x: [" },
    });
    mockedValidate.mockResolvedValueOnce({
      valid: false,
      stage: "yaml",
      message: "bad",
      line: 5,
      column: 7,
    });
    fireEvent.click(screen.getByRole("button", { name: /validate/i }));
    await waitFor(() => expect(screen.getByText(/\[yaml\]/)).toBeInTheDocument());
    expect(screen.getByText(/line 5, col 7/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
  });

  it("save calls upload then onSaved with new rule id", async () => {
    const onSaved = vi.fn();
    render(<UploadRuleDialog open onClose={() => {}} onSaved={onSaved} />);
    fireEvent.change(screen.getByTestId("yaml-editor"), {
      target: { value: "title: T" },
    });
    mockedValidate.mockResolvedValueOnce({ valid: true, rule_id: "rid-X", title: "T" });
    fireEvent.click(screen.getByRole("button", { name: /validate/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /save/i })).not.toBeDisabled(),
    );
    mockedUpload.mockResolvedValueOnce({ rule_id: "rid-X", title: "T", yaml_source: "title: T" });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith("rid-X"));
  });

  it("save error surfaces stage=compile message", async () => {
    render(<UploadRuleDialog open onClose={() => {}} onSaved={() => {}} />);
    fireEvent.change(screen.getByTestId("yaml-editor"), {
      target: { value: "title: T" },
    });
    mockedValidate.mockResolvedValueOnce({ valid: true, rule_id: "rid", title: "T" });
    fireEvent.click(screen.getByRole("button", { name: /validate/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /save/i })).not.toBeDisabled(),
    );
    mockedUpload.mockRejectedValueOnce(new Error("collision"));
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(screen.getByText(/collision/)).toBeInTheDocument());
  });
});
