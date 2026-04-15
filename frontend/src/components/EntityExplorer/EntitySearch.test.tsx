import { describe, it, expect, beforeEach, vi } from "vitest";
import { fireEvent, render, screen, act } from "@testing-library/react";
import { useEntityStore } from "@/stores/entity";
import { api } from "@/lib/api";
import { EntitySearch } from "./EntitySearch";

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn() },
  ApiError: class extends Error { constructor(public status: number, msg: string) { super(msg); } },
}));

const UUID = "11111111-2222-3333-4444-555555555555";
const UUID2 = "22222222-3333-4444-5555-666666666666";

beforeEach(() => {
  (api.get as unknown as ReturnType<typeof vi.fn>).mockReset();
  useEntityStore.setState(useEntityStore.getInitialState());
  localStorage.clear();
});

describe("EntitySearch", () => {
  it("renders a combobox input", () => {
    render(<EntitySearch />);
    expect(screen.getByRole("combobox")).toBeInTheDocument();
  });

  it("debounces input and shows results grouped by entity_type", async () => {
    vi.useFakeTimers();
    (api.get as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([
      { entity_type: "user", entity_value: "alice", entity_uuid: UUID },
      { entity_type: "ip", entity_value: "10.0.0.5", entity_uuid: UUID2 },
    ]);
    render(<EntitySearch />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "a" } });
    await act(async () => { vi.advanceTimersByTime(300); });
    vi.useRealTimers();
    await screen.findByText("alice");
    expect(screen.getByText("10.0.0.5")).toBeInTheDocument();
    expect(screen.getAllByRole("option").length).toBe(2);
  });

  it("Esc closes dropdown and restores focus to input", async () => {
    (api.get as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([
      { entity_type: "user", entity_value: "alice", entity_uuid: UUID },
    ]);
    render(<EntitySearch />);
    const input = screen.getByRole("combobox") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "alice" } });
    await screen.findByText("alice");
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(document.activeElement).toBe(input);
  });

  it("renders recent searches when input empty", () => {
    useEntityStore.getState().pushRecent({
      entity_type: "user", entity_value: "bob", entity_uuid: UUID,
    });
    render(<EntitySearch />);
    fireEvent.focus(screen.getByRole("combobox"));
    expect(screen.getByText(/Recent/i)).toBeInTheDocument();
    expect(screen.getByText("bob")).toBeInTheDocument();
  });

  it("Arrow Down/Up + Enter navigates to highlighted option", async () => {
    (api.get as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([
      { entity_type: "user", entity_value: "alice", entity_uuid: UUID },
      { entity_type: "ip", entity_value: "10.0.0.5", entity_uuid: UUID2 },
    ]);
    const pushSpy = vi.fn();
    const origPush = window.history.pushState.bind(window.history);
    window.history.pushState = (...args: Parameters<typeof origPush>) => {
      pushSpy(...args);
      return origPush(...args);
    };
    try {
      render(<EntitySearch />);
      const input = screen.getByRole("combobox") as HTMLInputElement;
      fireEvent.change(input, { target: { value: "a" } });
      await screen.findByText("alice");
      fireEvent.keyDown(input, { key: "ArrowDown" });
      fireEvent.keyDown(input, { key: "ArrowDown" });
      fireEvent.keyDown(input, { key: "ArrowUp" });
      fireEvent.keyDown(input, { key: "Enter" });
      expect(pushSpy).toHaveBeenCalled();
      const url = String(pushSpy.mock.calls[0][2]);
      expect(url).toContain("entity=");
    } finally {
      window.history.pushState = origPush;
    }
  });

  it("clicking an option (mousedown) navigates and closes", async () => {
    (api.get as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([
      { entity_type: "user", entity_value: "alice", entity_uuid: UUID },
    ]);
    render(<EntitySearch />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "a" } });
    const option = await screen.findByRole("option");
    fireEvent.mouseDown(option);
    expect(useEntityStore.getState().recent[0]?.entity_uuid).toBe(UUID);
  });

  it("blurring outside the container closes the dropdown", async () => {
    (api.get as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([
      { entity_type: "user", entity_value: "alice", entity_uuid: UUID },
    ]);
    render(
      <div>
        <EntitySearch />
        <button>outside</button>
      </div>,
    );
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "a" } });
    await screen.findByText("alice");
    fireEvent.blur(screen.getByRole("combobox"), { relatedTarget: screen.getByText("outside") });
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("renders 'No entities match' when query has results=[]", async () => {
    (api.get as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    render(<EntitySearch />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "zzz" } });
    // Wait for store to settle (debounce + fetch)
    await new Promise((r) => setTimeout(r, 350));
    expect(screen.getByText(/No entities match/i)).toBeInTheDocument();
  });
});
