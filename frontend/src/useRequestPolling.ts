import { useEffect } from "react";

/** One request at a time; pause hidden tabs and stop when the caller is idle. */
export function useRequestPolling(
  task: (signal: AbortSignal) => Promise<void>,
  enabled: boolean,
  poll: boolean,
  onError: (error: unknown) => void,
  intervalMs = 2000,
) {
  useEffect(() => {
    if (!enabled) return;
    let disposed = false;
    let inFlight = false;
    let failures = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    async function run() {
      if (disposed || inFlight || document.hidden) return;
      inFlight = true;
      controller = new AbortController();
      try {
        await task(controller.signal);
        failures = 0;
      } catch (error) {
        if (!disposed && !controller.signal.aborted) {
          failures += 1;
          onError(error);
        }
      } finally {
        inFlight = false;
        if (!disposed && poll && !document.hidden) {
          timer = setTimeout(run, Math.min(30000, intervalMs * 2 ** failures));
        }
      }
    }
    function visibilityChanged() {
      clearTimeout(timer);
      if (document.hidden) controller?.abort();
      else void run();
    }
    void run();
    document.addEventListener("visibilitychange", visibilityChanged);
    return () => {
      disposed = true;
      clearTimeout(timer);
      controller?.abort();
      document.removeEventListener("visibilitychange", visibilityChanged);
    };
  }, [task, enabled, poll, onError, intervalMs]);
}
