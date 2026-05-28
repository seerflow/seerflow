import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  SummaryStat,
  TBtn,
  AlertsFilterChip,
  StatusPill,
  MiniEntityIcon,
  PageBtn,
} from "./AlertConsoleParts";

describe("AlertConsoleParts", () => {
  describe("SummaryStat", () => {
    it("renders value and label", () => {
      render(<SummaryStat label="open" value="17" tone="crit" />);
      expect(screen.getByText("17")).toBeInTheDocument();
      expect(screen.getByText("open")).toBeInTheDocument();
    });
  });

  describe("TBtn", () => {
    it("renders children as a button", () => {
      render(<TBtn>Export ndjson</TBtn>);
      expect(screen.getByRole("button", { name: "Export ndjson" })).toBeInTheDocument();
    });

    it("primary variant still exposes the button role", () => {
      render(<TBtn primary>+ New rule</TBtn>);
      expect(screen.getByRole("button", { name: "+ New rule" })).toBeInTheDocument();
    });
  });

  describe("AlertsFilterChip", () => {
    it("shows label and value when set", () => {
      render(<AlertsFilterChip label="severity" value="crit · warn" />);
      expect(screen.getByText("severity")).toBeInTheDocument();
      expect(screen.getByText("crit · warn")).toBeInTheDocument();
    });

    it("shows the placeholder when empty", () => {
      render(<AlertsFilterChip label="entity" value="" placeholder="filter by entity…" />);
      expect(screen.getByText("filter by entity…")).toBeInTheDocument();
    });
  });

  describe("StatusPill", () => {
    it.each(["open", "triaging", "resolved", "suppressed"] as const)(
      "renders the %s status text",
      (status) => {
        render(<StatusPill status={status} />);
        expect(screen.getByText(status)).toBeInTheDocument();
      },
    );
  });

  describe("MiniEntityIcon", () => {
    it("renders an svg for a known kind", () => {
      const { container } = render(<MiniEntityIcon kind="user" />);
      expect(container.querySelector("svg")).toBeTruthy();
    });

    it("falls back for an unknown kind without throwing", () => {
      const { container } = render(<MiniEntityIcon kind="totally-unknown" />);
      expect(container.querySelector("svg")).toBeTruthy();
    });
  });

  describe("PageBtn", () => {
    it("renders the page label as a button", () => {
      render(<PageBtn>2</PageBtn>);
      expect(screen.getByRole("button", { name: "2" })).toBeInTheDocument();
    });

    it("supports a disabled state", () => {
      render(<PageBtn disabled>‹</PageBtn>);
      expect(screen.getByRole("button", { name: "‹" })).toBeDisabled();
    });
  });
});
