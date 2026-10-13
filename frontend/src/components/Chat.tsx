import {useEffect, useRef, useState} from "react";
import {Copy, Send, Square, X, History, ArrowLeft} from "lucide-react";
import {useApp} from "../context";
import {operationId, navigate} from "../api";
import type {Chat} from "../types";
import {SourceLinks} from "./Library";
import {AnswerText} from "./AnswerText";

export function ChatDialog({draft, documentId, close}: {draft: string; documentId: string; close: () => void}) {
  const {data, refresh, notify} = useApp();
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const controller = useRef<AbortController | null>(null);
  const pending = useRef<{key: string; id: string} | null>(null);
  const [question, setQuestion] = useState(draft);
  const [scope, setScope] = useState(documentId);
  const [chat, setChat] = useState<Chat | null>(null);
  const [live, setLive] = useState("");
  const [sent, setSent] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState(false);
  const [status, setStatus] = useState("");
  const answerArea = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const focused = document.activeElement as HTMLElement | null;
    dialog.current?.showModal();
    input.current?.focus();
    return () => {controller.current?.abort(); dialog.current?.close(); focused?.focus();};
  }, []);
  useEffect(() => {if (busy) answerArea.current?.scrollTo({top: answerArea.current.scrollHeight});}, [live, busy]);
  async function ask() {
    if (busy || question.trim().length < 2) return;
    const payload = {question: question.trim(), document_id: scope || null, parent_id: chat?.id || null};
    const key = JSON.stringify(payload);
    if (pending.current?.key !== key) pending.current = {key, id: operationId()};
    const ctl = new AbortController(); controller.current = ctl;
    setBusy(true); setError(""); setLive(""); setSent(question.trim()); setStatus("正在检索资料"); setHistory(false);
    try {
      const response = await fetch("/api/ask", {method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json"}, body: JSON.stringify({...payload, request_id: pending.current.id}), signal: ctl.signal});
      if (!response.ok) {const value = await response.json(); throw new Error(value.detail || "提问失败，请重试");}
      if (!response.body) throw new Error("浏览器不支持读取回复，请使用较新的浏览器");
      const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = ""; let completed = false;
      while (true) {
        const {value, done} = await reader.read();
        buffer += decoder.decode(value, {stream: !done});
        let boundary: number;
        while ((boundary = buffer.indexOf("\n\n")) >= 0) {
          const raw = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
          if (!raw.startsWith("data: ")) continue;
          const event = JSON.parse(raw.slice(6)) as {type: string; text?: string; message?: string; chat?: Chat};
          if (event.type === "status") setStatus(event.message || "正在回答");
          if (event.type === "delta") setLive(text => text + event.text);
          if (event.type === "error") throw new Error(event.message);
          if (event.type === "done" && event.chat) {setChat(event.chat); setLive(""); setSent(""); setQuestion(""); completed = true; pending.current = null; await refresh();}
        }
        if (done) break;
      }
      if (!completed) throw new Error("连接中断，回答尚未保存。可用同一个问题重试");
    } catch (e) {
      setError(ctl.signal.aborted ? "已停止，未完成的回答没有保存" : e instanceof Error ? e.message : "回答未完成，请重试");
    } finally {setBusy(false); setStatus(""); controller.current = null;}
  }
  return <dialog className="chat-dialog" ref={dialog} onCancel={e => {e.preventDefault(); close();}} aria-labelledby="chat-title">
    <header className="chat-header"><h2 id="chat-title">提问资料</h2><div className="row-actions"><button className="icon-button" aria-label={history ? "返回当前问答" : "问答历史"} onClick={() => setHistory(!history)}>{history ? <ArrowLeft size={18}/> : <History size={18}/>}</button><button className="icon-button" aria-label="关闭提问" onClick={close}><X size={20}/></button></div></header>
    <div className="chat-body" ref={answerArea}>{history ? <div className="chat-history"><h3>已保存的问答</h3>{data.chats.map(value => <button key={value.id} onClick={() => {setChat(value); setLive(""); setSent(""); setHistory(false);}}><strong>{value.question}</strong><span>{value.created_at.slice(0,16).replace("T"," ")}</span></button>)}{!data.chats.length && <p className="muted">还没有已保存的问答。</p>}</div> : <>
      {!chat && !live && !busy && !error && <p className="muted chat-empty">选择资料并输入具体问题。回答完成后可以展开出处、回到原文，或继续追问。</p>}
      {chat && !busy && !sent && <div className="chat-answer"><p className="chat-question">{chat.question}</p><AnswerText value={chat.answer}/><SourceLinks sources={chat.sources} onNavigate={close}/><div className="answer-footnote"><span>{chat.supported ? "出处定位已核对；结论仍需结合原文检查。" : "证据不足，请补充资料或调整问题。"}</span><button className="icon-button" aria-label="复制回答" onClick={() => void navigator.clipboard.writeText(chat.answer).then(() => notify("回答已复制")).catch(() => notify("复制失败，请选择文字后复制", true))}><Copy size={16}/></button></div></div>}
      {sent && <p className="chat-question">{sent}</p>}{live && <AnswerText value={live}/>} {busy && <p className="loading-line" role="status"><span className="spinner"/>{status}</p>}
      {error && <p role="alert" className="error">{error}</p>}
    </>}</div>
    <form className="chat-composer" onSubmit={e => {e.preventDefault(); void ask();}}><label className="chat-scope">资料范围<select aria-label="问答资料范围" value={scope} disabled={busy} onChange={e => {setScope(e.target.value); setChat(null);}}><option value="">全部资料</option>{data.documents.map(d => <option key={d.id} value={d.id}>{d.title}</option>)}</select></label>
      {!data.model.configured && <p className="muted small">需要先填写模型配置。<button type="button" className="text-button" onClick={() => {close(); navigate("settings");}}>打开设置</button></p>}
      <label className="sr-only" htmlFor="ask-question">{chat ? "追问内容" : "问题内容"}</label><textarea id="ask-question" ref={input} maxLength={2000} rows={3} value={question} placeholder={chat ? "继续追问，或点击新问题切换话题" : "例如：增量备份和差异备份有什么区别？"} disabled={busy} onChange={e => setQuestion(e.target.value)}/><div className="composer-actions"><button type="button" className="text-button" disabled={busy} onClick={() => {setChat(null); setLive(""); setSent(""); setError(""); input.current?.focus();}}>新问题</button>{busy ? <button type="button" onClick={() => controller.current?.abort()}><Square size={15}/>停止</button> : <button className="primary" type="submit" disabled={question.trim().length < 2 || !data.documents.length}><Send size={16}/>{chat ? "发送追问" : "发送问题"}</button>}</div>
    </form>
  </dialog>;
}
