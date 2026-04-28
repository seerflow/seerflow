export type Viewport = { scale: number; tx: number; ty: number };

export type ViewAction =
  | { kind: "zoomBy"; factor: number }
  | { kind: "wheelAt"; deltaY: number; ox: number; oy: number }
  | { kind: "panBy"; dx: number; dy: number }
  | { kind: "reset" };

export const MIN_SCALE = 0.5;
export const MAX_SCALE = 3;
export const INITIAL_VIEW: Viewport = { scale: 1, tx: 0, ty: 0 };

export function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n));
}

export function viewportReducer(state: Viewport, action: ViewAction): Viewport {
  switch (action.kind) {
    case "zoomBy": {
      const next = clamp(state.scale * action.factor, MIN_SCALE, MAX_SCALE);
      return { ...state, scale: next };
    }
    case "wheelAt": {
      const factor = Math.exp(-action.deltaY / 500);
      const next = clamp(state.scale * factor, MIN_SCALE, MAX_SCALE);
      if (next === state.scale) {
        return state;
      }
      const k = next / state.scale;
      return {
        scale: next,
        tx: action.ox - k * (action.ox - state.tx),
        ty: action.oy - k * (action.oy - state.ty),
      };
    }
    case "panBy":
      return { ...state, tx: state.tx + action.dx, ty: state.ty + action.dy };
    case "reset":
      return { ...INITIAL_VIEW };
  }
}
