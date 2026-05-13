import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { RuleSparkline } from "./RuleSparkline";

describe("RuleSparkline", () => {
  it("renders a polyline with one point per bucket", () => {
    const buckets = Array.from({ length: 24 }, (_, i) => ({
      bucket_start_ns: BigInt(i) * 3_600_000_000_000n,
      count: i % 3,
    }));
    render(<RuleSparkline buckets={buckets} />);
    const poly = document.querySelector("polyline");
    expect(poly).not.toBeNull();
    expect(poly!.getAttribute("points")!.split(" ")).toHaveLength(24);
  });

  it("renders flat baseline + tooltip when all counts are zero", () => {
    const buckets = Array.from({ length: 24 }, (_, i) => ({
      bucket_start_ns: BigInt(i) * 3_600_000_000_000n,
      count: 0,
    }));
    render(<RuleSparkline buckets={buckets} />);
    expect(screen.getByTitle("no recent matches")).toBeInTheDocument();
  });
});
