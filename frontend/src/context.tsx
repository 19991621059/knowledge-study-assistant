import {createContext, useContext, useState} from "react";
import type {AppState} from "./types";
export interface ContextValue {
  data: AppState; refresh: () => Promise<void>;
  notify: (message: string, error?: boolean) => void;
  openAsk: (draft?: string, documentId?: string) => void;
}
export const AppContext = createContext<ContextValue | null>(null);
export function useApp() {
  const value = useContext(AppContext);
  if (!value) throw new Error("学习状态未准备好");
  return value;
}
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function run<T>(action: () => Promise<T>): Promise<T | undefined> {
    if (busy) return undefined;
    setBusy(true); setError("");
    try {return await action();}
    catch (e) {setError(e instanceof Error ? e.message : "操作失败，请重试"); return undefined;}
    finally {setBusy(false);}
  }
  return {busy, error, run};
}
