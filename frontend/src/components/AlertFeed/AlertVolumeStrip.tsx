/**
 * AlertVolumeStrip — stacked info/warn/crit SVG bars over the 24h window
 * (S-336), ported from `DashAlertsList`'s `AlertVolumeStrip` in the mockup.
 *
 * The strip is a deterministic demo visualisation: the alert store does not
 * expose a per-bucket volume series, so AC4's "SVG strip à la AlertVolumeStrip"
 * is honoured with the mockup's generator. It renders stably regardless of the
 * live alert count (no console errors on an empty feed) and adds no uPlot /
 * canvas teardown noise to the test suite.
 */

const N = 96;
const W = 980;
const H = 36;

function buildBars(): Array<[number, number, number]> {
  return Array.from({ length: N }, (_, i) => {
    const t = i / N;
    const base = 2 + 1.5 * Math.sin(t * 6.0) + 1.0 * Math.sin(t * 13.3 + 1.1);
    const burst = i > 70 && i < 84 ? 4 + (i - 70) * 0.4 : 0;
    const info = Math.max(0.6, base);
    const warn = Math.max(0, base * 0.5 + (i > 50 && i < 65 ? 1.4 : 0));
    const crit = Math.max(0, burst);
    return [info, warn, crit];
  });
}

export function AlertVolumeStrip(): JSX.Element {
  const bars = buildBars();
  const totals = bars.map((b) => b[0] + b[1] + b[2]);
  const max = Math.max(...totals) * 1.1;
  const bw = (W - (N - 1) * 1.5) / N;
  const sH = (v: number): number => (v / max) * H;

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      style={{ display: "block", height: 36 }}
      data-testid="alert-volume-strip"
    >
      {bars.map(([info, warn, crit], i) => {
        const x = i * (bw + 1.5);
        let y = H;
        const segs: JSX.Element[] = [];
        if (info > 0) {
          const sh = sH(info);
          y -= sh;
          segs.push(
            <rect key={`i${i}`} x={x} y={y} width={bw} height={sh} fill="color-mix(in oklch, var(--text-3) 35%, transparent)" />,
          );
        }
        if (warn > 0) {
          const sh = sH(warn);
          y -= sh;
          segs.push(
            <rect key={`w${i}`} x={x} y={y} width={bw} height={sh} fill="color-mix(in oklch, var(--warn) 75%, transparent)" />,
          );
        }
        if (crit > 0) {
          const sh = sH(crit);
          y -= sh;
          segs.push(<rect key={`c${i}`} x={x} y={y} width={bw} height={sh} fill="var(--crit)" />);
        }
        return segs;
      })}
    </svg>
  );
}
