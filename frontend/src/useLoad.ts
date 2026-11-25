import { useCallback, useEffect, useState } from "react";
import { ApiError } from "./api/client";

export interface LoadState<T> {
  readonly data: T | null;
  readonly error: ApiError | null;
  readonly loading: boolean;
  readonly reload: () => void;
}

interface Settled<T> {
  load: unknown;
  tick: number;
  data: T | null;
  error: ApiError | null;
}

/** Run an abortable loader whenever `load` (a memoised callback) changes. Unmount/changes abort the in-flight request. */
export function useLoad<T>(load: (signal: AbortSignal) => Promise<T>): LoadState<T> {
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setSettled({ load, tick, data, error: null });
      })
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        const error = e instanceof ApiError ? e : new ApiError(0, "UNKNOWN", "Something went wrong. Please try again.");
        setSettled({ load, tick, data: null, error });
      });
    return () => controller.abort();
  }, [load, tick]);

  const reload = useCallback(() => setTick((n) => n + 1), []);
  const current = settled !== null && settled.load === load && settled.tick === tick;
  return {
    data: current ? settled.data : null,
    error: current ? settled.error : null,
    loading: !current,
    reload,
  };
}
