function hashToUnit(key: string): number {
  // FNV-1a 32-bit, mapped to [0, 1)
  let h = 2166136261 >>> 0;
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 0x100000000;
}

export type Theme = "light" | "dark";

export function entitySourceColor(key: string, theme: Theme = "light"): string {
  const hue = Math.floor(hashToUnit(key) * 360);
  const lightness = theme === "dark" ? 60 : 45;
  return `hsl(${hue}, 65%, ${lightness}%)`;
}
