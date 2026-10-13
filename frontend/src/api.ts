export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch("/api" + path, {
    ...options, credentials: "same-origin", cache: "no-store",
    headers: {...(options.body instanceof FormData ? {} : {"Content-Type": "application/json"}), ...options.headers},
  });
  const value = await response.json();
  if (!response.ok) {
    if (response.status === 401 && path !== "/login") window.dispatchEvent(new Event("session-expired"));
    throw new Error(typeof value.detail === "string" ? value.detail : "输入内容不符合要求，请检查后重试");
  }
  return value as T;
}
export function post<T>(path: string, body: unknown = {}) {
  return api<T>(path, {method: "POST", body: JSON.stringify(body)});
}
export function put<T>(path: string, body: unknown) {
  return api<T>(path, {method: "PUT", body: JSON.stringify(body)});
}
export const operationId = () => crypto.randomUUID();
export const navigate = (path: string) => {window.location.hash = path;};
export function route() {
  const [path, query] = (window.location.hash.slice(1) || "today").split("?");
  return {path, params: new URLSearchParams(query)};
}
