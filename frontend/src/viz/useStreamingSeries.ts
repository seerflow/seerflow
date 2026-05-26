import { useState, useCallback, useRef } from "react";

// --------------------------------------------------------------------------
// Types
// --------------------------------------------------------------------------

/** Shape returned by toArrays() / hook data */
export interface SeriesArrays {
  /** Unix timestamps (seconds or ms — caller decides unit) */
  timestamps: number[];
  /** Parallel value arrays: values[seriesIndex][sampleIndex] */
  values: number[][];
}

/** Fixed-capacity circular ring buffer */
export interface RingBuffer<T = number> {
  readonly capacity: number;
  /** Current number of valid samples (≤ capacity) */
  length: number;
  /** Push a new sample, overwriting oldest if full */
  push(timestamp: number, value: T): void;
  /** Snapshot ordered arrays (oldest → newest) */
  toArrays(): SeriesArrays;
  /** Reset to empty */
  clear(): void;
}

// --------------------------------------------------------------------------
// createRingBuffer — pure, no React dependency
// --------------------------------------------------------------------------

/**
 * Create a fixed-capacity circular ring buffer for streaming time-series.
 *
 * The buffer stores `capacity` samples.  When full, `push()` overwrites the
 * oldest sample.  `toArrays()` returns new ordered arrays on every call.
 *
 * Multi-series example:
 *   const buf = createRingBuffer<[number, number]>(900)
 *   buf.push(ts, [infoCount, warnCount])
 *   const { timestamps, values } = buf.toArrays()
 *   // values[0] = info series, values[1] = warn series
 */
export function createRingBuffer<T = number>(capacity: number): RingBuffer<T> {
  if (capacity < 1) throw new RangeError("capacity must be ≥ 1");

  const tsBuf = new Float64Array(capacity);
  // Determine series count lazily on first push; start with 1 placeholder.
  let numSeries = 1;
  let valBufs: Float64Array[] = [new Float64Array(capacity)];

  let head = 0; // next write index
  let count = 0;

  function push(timestamp: number, value: T): void {
    // Determine actual series from value shape
    const isArray = Array.isArray(value);
    const n = isArray ? (value as number[]).length : 1;

    // Lazily expand valBufs on first push
    if (n !== numSeries) {
      numSeries = n;
      valBufs = Array.from({ length: numSeries }, () => new Float64Array(capacity));
    }

    tsBuf[head] = timestamp;
    if (isArray) {
      for (let s = 0; s < numSeries; s++) {
        valBufs[s][head] = (value as number[])[s];
      }
    } else {
      valBufs[0][head] = value as unknown as number;
    }

    head = (head + 1) % capacity;
    if (count < capacity) count++;
  }

  function toArrays(): SeriesArrays {
    const len = count;
    const timestamps = new Array<number>(len);
    const values: number[][] = Array.from({ length: numSeries }, () => new Array<number>(len));

    // Start reading from oldest valid sample
    const start = count < capacity ? 0 : head;
    for (let i = 0; i < len; i++) {
      const idx = (start + i) % capacity;
      timestamps[i] = tsBuf[idx];
      for (let s = 0; s < numSeries; s++) {
        values[s][i] = valBufs[s][idx];
      }
    }
    return { timestamps, values };
  }

  function clear(): void {
    head = 0;
    count = 0;
    tsBuf.fill(0);
    valBufs.forEach((b) => b.fill(0));
  }

  return {
    get capacity() { return capacity; },
    get length() { return count; },
    push,
    toArrays,
    clear,
  };
}

// --------------------------------------------------------------------------
// useStreamingSeries — React hook wrapping the ring buffer
// --------------------------------------------------------------------------

interface UseStreamingSeriesOptions {
  /** Number of samples to keep in the ring buffer (default 900 = 15min@1s) */
  capacity?: number;
}

interface UseStreamingSeriesResult<T> {
  /** Current ordered snapshot — new reference after every push */
  data: SeriesArrays;
  /** Buffer capacity */
  capacity: number;
  /** Push a new sample into the buffer */
  push: (timestamp: number, value: T) => void;
  /** Clear all samples */
  clear: () => void;
}

/**
 * React hook: fixed-size streaming ring buffer.
 *
 * Internally manages a `RingBuffer` in a ref so `push` never re-creates
 * the buffer.  State holds only the latest snapshot so React can schedule
 * a re-render.
 *
 * @example
 *   const { data, push } = useStreamingSeries({ capacity: 60 })
 *   // on WS message:
 *   push(Date.now() / 1000, eventCount)
 *   // in uPlot update:
 *   u.setData([data.timestamps, ...data.values])
 */
export function useStreamingSeries<T = number>(
  options: UseStreamingSeriesOptions = {},
): UseStreamingSeriesResult<T> {
  const cap = options.capacity ?? 900;

  // The ring buffer lives in a ref — never recreated
  const bufRef = useRef<RingBuffer<T>>(createRingBuffer<T>(cap));

  const [data, setData] = useState<SeriesArrays>(() => bufRef.current.toArrays());

  const push = useCallback((timestamp: number, value: T) => {
    bufRef.current.push(timestamp, value);
    setData(bufRef.current.toArrays());
  }, []);

  const clear = useCallback(() => {
    bufRef.current.clear();
    setData(bufRef.current.toArrays());
  }, []);

  return { data, capacity: cap, push, clear };
}
