import { describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { useToast } from "./useToast";
import { toast } from "sonner";

describe("useToast", () => {
  it("success passes 3000ms duration", () => {
    useToast().success("hi");
    expect(toast.success).toHaveBeenCalledWith("hi", { duration: 3000 });
  });
  it("error passes 5000ms duration", () => {
    useToast().error("bad");
    expect(toast.error).toHaveBeenCalledWith("bad", { duration: 5000 });
  });
});
