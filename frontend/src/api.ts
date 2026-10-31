import { useCallback, useEffect, useState, useRef } from "react";
export type Data = Record<string, any>;
export async function api(path: string, options: RequestInit = {}) {
  const r = await fetch("/api" + path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await r.json();
  if (!r.ok) {
    const detail = data.detail;
    const message = Array.isArray(detail)
      ? detail
          .map(
            (item: { loc?: (string | number)[]; msg?: string }) =>
              `${item.loc?.filter((part) => part !== "body").join(".") || "Input"}: ${item.msg || "Invalid value"}`,
          )
          .join("; ")
      : typeof detail === "string"
        ? detail
        : "Something went wrong";
    throw new Error(message);
  }
  return data;
}
export const post = (path: string, body: Data = {}) =>
  api(path, { method: "POST", body: JSON.stringify(body) });
export function useData(path: string) {
  const [data, setData] = useState<Data | null>(null),
    [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  const load = useCallback(() => {
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    setData(null);
    setError("");
    api(path, { signal: next.signal })
      .then(setData)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
  }, [path]);
  useEffect(() => {
    load();
    return () => controller.current?.abort();
  }, [load]);
  return { data, error, load };
}
