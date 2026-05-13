import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { SourceHealthPreview } from "./SourceHealthPreview";

describe("SourceHealthPreview", () => {
  it("renders the preview card with a 'Preview' badge", () => {
    const { getByText } = render(<SourceHealthPreview />);
    expect(getByText(/Preview/i)).toBeInTheDocument();
    expect(getByText(/Live source health coming/i)).toBeInTheDocument();
  });
});
