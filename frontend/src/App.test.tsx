import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "./main";

const example = {
  id: "case-1",
  account_id: "acme",
  question: "Investigate 403 failures",
  status: "failed",
  phase: "Manual review required",
  created_at: 1,
  result: null,
  evidence: [],
  guardrail_events: [],
  error: "Provider safety block: request blocked",
  retryable: false,
  draft: null,
  receipt: null,
};
let record = { ...example };
let requests: string[];
beforeEach(() => {
  vi.useFakeTimers();
  record = { ...example };
  requests = [];
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: false,
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      requests.push(url);
      const data =
        url === "/api/health"
          ? { mode: "live", auth_mode: "demo" }
          : url === "/api/me"
            ? { name: "Alex Morgan" }
            : url === "/api/accounts"
              ? [{ id: "acme", name: "Acme Industries", product_version: "3" }]
              : url === "/api/cases"
                ? [{ ...record }]
                : url.endsWith("/retry")
                  ? { id: record.id, status: "queued" }
                  : { spans: [], audit: [] };
      return { ok: true, json: async () => data };
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
const settle = () =>
  act(async () => {
    for (let i = 0; i < 10; i++) await Promise.resolve();
  });
const count = (path: string) => requests.filter((x) => x === path).length;

test("idle case does not poll identity, accounts, cases or unopened trace", async () => {
  render(<App />);
  await settle();
  expect(screen.queryByText("Retry investigation")).toBeNull();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(20000);
  });
  expect(count("/api/me")).toBe(1);
  expect(count("/api/accounts")).toBe(1);
  expect(count("/api/cases")).toBe(1);
  expect(count("/api/cases/case-1/trace")).toBe(0);
  fireEvent.click(screen.getByRole("tab", { name: "Execution trace" }));
  await settle();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10000);
  });
  expect(count("/api/cases/case-1/trace")).toBe(1);
});

test("active case polls cases and stops after completion", async () => {
  record = { ...example, status: "running", error: "", retryable: false };
  render(<App />);
  await settle();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(4000);
  });
  expect(count("/api/cases")).toBeGreaterThan(2);
  expect(count("/api/accounts")).toBe(1);
  expect(count("/api/me")).toBe(1);
  expect(count("/api/cases/case-1/trace")).toBe(0);
  record.status = "completed";
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2000);
  });
  const before = requests.length;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10000);
  });
  expect(requests.length).toBe(before);
});

test("retry starts polling again from an idle failed state", async () => {
  record = { ...example, error: "Connection failed", retryable: true };
  render(<App />);
  await settle();
  record.status = "running";
  record.error = "";
  fireEvent.click(screen.getByRole("button", { name: "Retry investigation" }));
  await settle();
  expect(count("/api/cases/case-1/retry")).toBe(1);
  const before = count("/api/cases");
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2000);
  });
  expect(count("/api/cases")).toBeGreaterThan(before);
});
