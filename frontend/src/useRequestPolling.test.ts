import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { useRequestPolling } from "./useRequestPolling";

beforeEach(() => {
  vi.useFakeTimers();
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: false,
  });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});
const flush = () =>
  act(async () => {
    await Promise.resolve();
  });

test("idle views fetch once, active views poll, terminal states stop", async () => {
  const task = vi.fn().mockResolvedValue(undefined),
    error = vi.fn();
  const { rerender } = renderHook(
    ({ poll }) => useRequestPolling(task, true, poll, error),
    { initialProps: { poll: false } },
  );
  await flush();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10000);
  });
  expect(task).toHaveBeenCalledTimes(1);
  rerender({ poll: true });
  await flush();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(4000);
  });
  expect(task).toHaveBeenCalledTimes(4);
  rerender({ poll: false });
  await flush();
  const count = task.mock.calls.length;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10000);
  });
  expect(task).toHaveBeenCalledTimes(count);
});

test("slow requests never overlap and are aborted on cleanup", async () => {
  let resolve!: () => void;
  const task = vi.fn(
    (_signal: AbortSignal) =>
      new Promise<void>((r) => {
        resolve = r;
      }),
  );
  const { unmount } = renderHook(() =>
    useRequestPolling(task, true, true, vi.fn()),
  );
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10000);
  });
  expect(task).toHaveBeenCalledTimes(1);
  unmount();
  expect(task.mock.calls[0][0].aborted).toBe(true);
  resolve();
  await flush();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10000);
  });
  expect(task).toHaveBeenCalledTimes(1);
});

test("hidden tabs pause and resume polling when visible", async () => {
  const task = vi.fn().mockResolvedValue(undefined),
    error = vi.fn();
  renderHook(() => useRequestPolling(task, true, true, error));
  await flush();
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: true,
  });
  act(() => document.dispatchEvent(new Event("visibilitychange")));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10000);
  });
  expect(task).toHaveBeenCalledTimes(1);
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: false,
  });
  act(() => document.dispatchEvent(new Event("visibilitychange")));
  await flush();
  expect(task).toHaveBeenCalledTimes(2);
});

test("request failures back off instead of overlapping requests", async () => {
  const task = vi.fn().mockRejectedValue(new Error("offline")),
    error = vi.fn();
  renderHook(() => useRequestPolling(task, true, true, error));
  await flush();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3999);
  });
  expect(task).toHaveBeenCalledTimes(1);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1);
  });
  expect(task).toHaveBeenCalledTimes(2);
  expect(error).toHaveBeenCalledTimes(2);
});
