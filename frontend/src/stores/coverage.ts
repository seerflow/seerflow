import { create } from "zustand";
import { api } from "@/lib/api";
import type { AttackCoverageResponse } from "@/lib/types";

export interface CoverageState {
  data: AttackCoverageResponse | null;
  loading: boolean;
  error: string | null;
  fetch: (since?: string, until?: string) => Promise<void>;
}

export const useCoverageStore = create<CoverageState>((set) => ({
  data: null,
  loading: false,
  error: null,
  fetch: async (since, until) => {
    set({ loading: true, error: null });
    try {
      const params = new URLSearchParams();
      if (since) params.set("since", since);
      if (until) params.set("until", until);
      const qs = params.toString();
      const path = `/api/v1/attack/coverage${qs ? `?${qs}` : ""}`;
      const data = await api.get<AttackCoverageResponse>(path);
      set({ data, loading: false });
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e), loading: false });
    }
  },
}));
