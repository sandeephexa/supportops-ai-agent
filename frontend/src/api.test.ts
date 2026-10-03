import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ApiError, fetchJson, formatEvidence, useApi } from "./api";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

test("malformed evidence renders unchanged instead of crashing", () => {
  expect(formatEvidence("{broken JSON")).toBe("{broken JSON");
  expect(formatEvidence('{"jobs":23}')).toBe('{\n  "jobs": 23\n}');
});

test("HTTP errors retain status for reauthentication and handle non-JSON bodies", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => {
        throw new SyntaxError();
      },
    }),
  );
  await expect(fetchJson("/api/me")).rejects.toMatchObject({ status: 401 });
  vi.mocked(fetch).mockResolvedValue({
    ok: false,
    status: 403,
    json: async () => ({ detail: "Not authorized" }),
  } as Response);
  await expect(fetchJson("/api/me")).rejects.toEqual(
    new ApiError("Not authorized", 403),
  );
});

test("a timed-out mutation is aborted but never automatically retried", async () => {
  vi.useFakeTimers();
  vi.stubGlobal(
    "fetch",
    vi.fn(
      (_url, options) =>
        new Promise((_resolve, reject) => {
          options.signal.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        }),
    ),
  );
  const request = fetchJson("/api/cases", { method: "POST" }, 50);
  const assertion = expect(request).rejects.toThrow(
    "check its status before submitting again",
  );
  await vi.advanceTimersByTimeAsync(50);
  await assertion;
  expect(fetch).toHaveBeenCalledTimes(1);
});

test("changing identity cancels stale requests and prevents late responses", async () => {
  let resolve!: (response: Response) => void;
  let signal!: AbortSignal;
  vi.stubGlobal(
    "fetch",
    vi.fn((_url, options) => {
      signal = options.signal;
      return new Promise((r) => {
        resolve = r;
      });
    }),
  );
  const hook = renderHook(({ user }) => useApi("demo", "", user), {
    initialProps: { user: "engineer-acme" },
  });
  const request = hook.result.current("/cases?summary=true");
  const assertion = expect(request).rejects.toMatchObject({
    name: "AbortError",
  });
  hook.rerender({ user: "viewer-acme" });
  expect(signal.aborted).toBe(true);
  await act(async () =>
    resolve({ ok: true, json: async () => [{ id: "stale" }] } as Response),
  );
  await assertion;
});
