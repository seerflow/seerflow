import { create } from "zustand";

export interface OpenCell {
  tactic: string;
  technique: string;
}

export interface DrilldownState {
  openCell: OpenCell | null;
  open: (tactic: string, technique: string) => void;
  close: () => void;
}

export const useDrilldownStore = create<DrilldownState>((set, get) => ({
  openCell: null,
  open: (tactic, technique) => {
    const cur = get().openCell;
    if (cur && cur.tactic === tactic && cur.technique === technique) return;
    set({ openCell: { tactic, technique } });
  },
  close: () => {
    if (get().openCell === null) return;
    set({ openCell: null });
  },
}));
