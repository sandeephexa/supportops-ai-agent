import { useCallback, useEffect, useRef } from "react";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

export async function fetchJson<T>(
  path: string,
  options: RequestInit = {},
  timeoutMs = 15000,
): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  options.signal?.addEventListener("abort", abort, { once: true });
  if (options.signal?.aborted) controller.abort();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  try {
    const response = await fetch(path, {
      ...options,
      signal: controller.signal,
    });
    const body: unknown = await response.json().catch(() => null);
    controller.signal.throwIfAborted();
    if (!response.ok) {
      const detail =
        body && typeof body === "object" && "detail" in body
          ? body.detail
          : null;
      throw new ApiError(
        typeof detail === "string"
          ? detail
          : "The request could not be completed.",
        response.status,
      );
    }
    if (body === null)
      throw new Error(
        "The server returned an invalid response. Refresh and try again.",
      );
    return body as T;
  } catch (error) {
    if (timedOut)
      throw new Error(
        "The request timed out. Refresh to check its status before submitting again.",
      );
    throw error;
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", abort);
  }
}

export function useApi(
  authMode: string | undefined,
  token: string,
  user: string,
) {
  const scope = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    scope.current = controller;
    return () => controller.abort();
  }, [authMode, token, user]);
  return useCallback(
    async <T>(path: string, options: RequestInit = {}): Promise<T> => {
      const headers = new Headers(options.headers);
      if (options.body) headers.set("Content-Type", "application/json");
      if (authMode === "oidc") headers.set("Authorization", `Bearer ${token}`);
      else headers.set("X-Demo-User", user);
      return fetchJson<T>(`/api${path}`, {
        ...options,
        headers,
        signal: AbortSignal.any([
          scope.current!.signal,
          ...(options.signal ? [options.signal] : []),
        ]),
      });
    },
    [authMode, token, user],
  );
}

export function formatEvidence(content: string): string {
  if (!/^[\s]*[\[{]/.test(content)) return content;
  try {
    return JSON.stringify(JSON.parse(content), null, 2);
  } catch {
    return content;
  }
}
