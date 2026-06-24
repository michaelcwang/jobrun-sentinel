import { useCallback, useEffect, useRef, useState } from "react";

export function useAsync<T>(loader: (signal: AbortSignal) => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const dataRef = useRef<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const setStoredData = useCallback((value: T | null) => {
    dataRef.current = value;
    setData(value);
  }, []);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const hasExistingData = dataRef.current !== null;
    // Polling views keep the previous payload mounted while a refresh is in flight.
    // This avoids page-level flicker when live dashboard data updates.
    if (hasExistingData) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);
    loader(controller.signal)
      .then((value) => {
        if (active) setStoredData(value);
      })
      .catch((err: Error) => {
        if (err.name === "AbortError") return;
        if (active) setError(err.message);
      })
      .finally(() => {
        if (active) {
          setLoading(false);
          setRefreshing(false);
        }
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, deps);

  return { data, error, loading, refreshing, setData: setStoredData };
}
