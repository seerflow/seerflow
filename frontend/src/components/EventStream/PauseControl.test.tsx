import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PauseControl } from "./PauseControl";
import { MAX_PAUSED_BUFFER } from "@/stores/events";

describe("PauseControl", () => {
  it("shows Pause when not paused", () => {
    render(<PauseControl paused={false} bufferedCount={0} onToggle={() => undefined} />);
    expect(screen.getByRole("button", { name: /pause/i })).toBeInTheDocument();
  });

  it("shows Resume + buffered count when paused", () => {
    render(<PauseControl paused={true} bufferedCount={37} onToggle={() => undefined} />);
    expect(screen.getByRole("button", { name: /resume.*37 buffered/i })).toBeInTheDocument();
  });

  it("shows MAX+ when buffered count hit cap", () => {
    render(<PauseControl paused={true} bufferedCount={MAX_PAUSED_BUFFER} onToggle={() => undefined} />);
    expect(screen.getByText(new RegExp(`${MAX_PAUSED_BUFFER}\\+`))).toBeInTheDocument();
  });

  it("calls onToggle on click", () => {
    const onToggle = vi.fn();
    render(<PauseControl paused={false} bufferedCount={0} onToggle={onToggle} />);
    fireEvent.click(screen.getByRole("button"));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});
