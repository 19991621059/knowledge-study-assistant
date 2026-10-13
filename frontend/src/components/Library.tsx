import {useEffect, useRef, useState} from "react";
import {ArrowLeft, ArrowRight, Check, Search, Star, Upload, FileText, MessageSquare, ChevronDown} from "lucide-react";
import {api, post, put, navigate} from "../api";
import {useApp, useAction} from "../context";
import {ContentBlocks} from "./ContentBlocks";
import type {Chunk, ContentBlock, Source} from "../types";

export function SourceLinks({sources, onNavigate}: {sources: Source[]; onNavigate?: () => void}) {
  const {data} = useApp();
  return <div className="source-links">{sources.map((source, i) => {
    const chunk = data.chunks.find(c => c.id === source.chunk_id);
    const doc = data.documents.find(d => d.id === chunk?.document_id);
    return <details key={source.chunk_id + i}>
      <summary>{source.label ? `[${source.label}] ` : "出处："}{source.document_title || doc?.title || "已删除的资料"} · {source.section}{doc?.format === "pdf" ? ` · 第${source.page}页` : ""}</summary>
      <blockquote>{source.quote}</blockquote>
      {chunk && <button className="text-button" onClick={() => {onNavigate?.(); navigate("reader/" + source.chunk_id);}}>定位到原文 <ArrowRight size={14}/></button>}
    </details>;
  })}</div>;
}

export function Library() {
  const {data, refresh, notify} = useApp();
  const {busy, error, run} = useAction();
  const fileInput = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Chunk[]>([]);
  useEffect(() => {
    if (query.length < 2) {setResults([]); return;}
    const controller = new AbortController();
    const delay = setTimeout(() => {
      api<Chunk[]>("/search?q=" + encodeURIComponent(query), {signal: controller.signal})
        .then(setResults).catch(e => {if (!controller.signal.aborted) notify(e.message, true);});
    }, 250);
    return () => {clearTimeout(delay); controller.abort();};
  }, [query]);
  async function importFiles(files: FileList | null) {
    if (!files) return;
    await run(async () => {
      for (const file of Array.from(files)) {
        const body = new FormData(); body.append("file", file);
        const result = await api<{duplicate: boolean}>("/documents", {method: "POST", body});
        notify(result.duplicate ? `${file.name}已存在，没有重复导入` : `${file.name}已导入`);
        await refresh();
      }
    });
    if (fileInput.current) fileInput.current.value = "";
  }
  async function openReader(documentId: string) {
    await run(async () => {
      const position = await api<{chunk_id: string}>("/last-position");
      const chunks = data.chunks.filter(chunk => chunk.document_id === documentId);
      const recent = chunks.filter(chunk => chunk.updated_at).sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""))[0];
      const target = chunks.find(chunk => chunk.id === position.chunk_id) || recent || chunks[0];
      if (target) navigate("reader/" + target.id);
    });
  }
  return <>
    <header className="page-heading"><div><h1>资料库</h1><p>原文、练习与学习记录按资料关联。</p></div><button className="primary" disabled={busy} onClick={() => fileInput.current?.click()}><Upload size={17}/>{busy ? "正在导入" : "导入资料"}</button></header>
    <input ref={fileInput} className="sr-only" type="file" aria-label="选择资料文件" accept=".txt,.md,.pdf,.docx,.json" multiple onChange={e => void importFiles(e.target.files)}/>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="library-toolbar"><label className="search-field"><Search size={17}/><input aria-label="搜索资料正文" placeholder="搜索资料正文" value={query} onChange={e => setQuery(e.target.value)}/></label><button disabled={busy} onClick={() => void run(async () => {await post("/examples"); await refresh(); notify("原创示例资料和3道示例题已导入");})}>导入示例</button></div>
    <p className="muted small">支持 TXT、Markdown、文字 PDF、DOCX 和指定 JSON 资料包；每个文件最多20MB。扫描 PDF 需先做 OCR。</p>
    {query.length >= 2 ? <section aria-label="搜索结果"><h2>搜索结果 · {results.length}</h2>{results.map(chunk => <button className="document-row result-row" key={chunk.id} onClick={() => navigate("reader/" + chunk.id)}><div><strong>{chunk.section}</strong><p>{chunk.text?.slice(0, 150)}</p></div><ArrowRight size={17}/></button>)}{!results.length && <p className="empty">没有匹配的文字，请调整关键词。</p>}</section> : <div className="document-list">{data.documents.map(doc => {
      const completed = data.chunks.filter(c => c.document_id === doc.id && c.completed).length;
      return <div className="document-row" key={doc.id}><FileText size={21}/><div className="grow"><h2>{doc.title}</h2><p>{doc.format.toUpperCase()} · {doc.chunk_count}个阅读片段 · {doc.question_count}道练习 · 已读{completed}个</p></div><div className="row-actions"><button disabled={busy} onClick={() => void openReader(doc.id)}>阅读</button><button onClick={() => navigate("practice?doc=" + doc.id + "&generate=1")}>生成练习</button></div></div>;
    })}{!data.documents.length && <div className="empty"><h2>先导入一份资料</h2><p>可以选择自己的文件，或用原创示例体验阅读、练习和计划。</p></div>}</div>}
  </>;
}

function blocks(text: string): ContentBlock[] {
  const paragraphs = text.split(/\n\s*\n/);
  return paragraphs.flatMap((part, i): ContentBlock[] => {
    const lines = part.trim().split("\n");
    if (!part.trim()) return [];
    if (/^#{1,6}\s/.test(part)) {
      const [first, ...rest] = lines;
      return [{type: "heading", text: first.replace(/^#{1,6}\s/, ""), id: "block" + i}, ...(rest.length ? [{type: "paragraph", text: rest.join("\n"), id: "body" + i}] : [])];
    }
    if (lines.every(line => /^[-*]\s/.test(line))) return [{type: "list", items: lines.map(line => line.slice(2)), id: "block" + i}];
    return [{type: "paragraph", text: part, id: "block" + i}];
  });
}

export function Reader({id}: {id: string}) {
  const {data, refresh, notify, openAsk} = useApp();
  const {busy, error, run} = useAction();
  const [content, setContent] = useState<Chunk | null>(null);
  const [loadError, setLoadError] = useState("");
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [directory, setDirectory] = useState(false);
  const current = data.chunks.find(c => c.id === id);
  const doc = data.documents.find(d => d.id === current?.document_id);
  const siblings = data.chunks.filter(c => c.document_id === current?.document_id);
  const index = siblings.findIndex(c => c.id === id);
  useEffect(() => {
    const controller = new AbortController();
    setContent(null); setLoadError("");
    api<Chunk>("/chunks/" + id, {signal: controller.signal}).then(value => {
      setContent(value); requestAnimationFrame(() => window.scrollTo(0, value.offset || 0));
    }).catch(e => {if (!controller.signal.aborted) setLoadError(e.message);});
    return () => controller.abort();
  }, [id, loadAttempt]);
  useEffect(() => {
    if (!content) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let last = window.scrollY;
    const save = () => {void put("/reading/" + id, {offset: Math.round(last)}).catch(e => notify("阅读位置保存失败：" + e.message, true));};
    const scroll = () => {last = window.scrollY; clearTimeout(timer); timer = setTimeout(save, 600);};
    window.addEventListener("scroll", scroll, {passive: true});
    return () => {window.removeEventListener("scroll", scroll); clearTimeout(timer); save();};
  }, [id, content?.id]);
  if (!current) return <div className="empty"><h1>资料未找到</h1><button onClick={() => navigate("library")}>返回资料库</button></div>;
  return <>
    <div className="reader-heading"><button className="text-button" onClick={() => navigate("library")}><ArrowLeft size={17}/>资料库</button><span>{doc?.title}</span><button className="directory-toggle" aria-expanded={directory} onClick={() => setDirectory(!directory)}>目录 <ChevronDown size={15}/></button></div>
    <div className="reader-layout"><aside className={"directory " + (directory ? "open" : "")} aria-label="资料目录"><h2>阅读目录</h2>{siblings.map((chunk, i) => <button aria-current={id === chunk.id ? "location" : undefined} className={id === chunk.id ? "selected" : ""} key={chunk.id} onClick={() => {navigate("reader/" + chunk.id); setDirectory(false);}}><span>{i+1}</span><span className="grow">{chunk.section}</span>{!!chunk.completed && <Check size={14} aria-label="已读"/>}</button>)}</aside>
    <article className="reader-content"><div className="eyebrow">片段{index+1} / {siblings.length}{doc?.format === "pdf" ? ` · 原文件第${current.page}页` : ""}</div><h1>{current.section}</h1><div className="reader-tools"><button disabled={busy} onClick={() => void run(async () => {await put("/reading/" + id, {favorite: !current.favorite}); await refresh();})}><Star size={16} fill={current.favorite ? "currentColor" : "none"}/>{current.favorite ? "已收藏" : "收藏片段"}</button><a className="button-link" href={"/api/documents/" + current.document_id + "/original"} download>下载原文件</a><button onClick={() => openAsk(`请解释“${current.section}”的关键内容。`, current.document_id)}><MessageSquare size={16}/>提问这份资料</button></div>
      {content ? <ContentBlocks blocks={blocks(content.text || "")} imageUrl={() => ""}/> : loadError ? <p role="alert" className="error">读取原文失败：{loadError} <button onClick={() => setLoadAttempt(value => value + 1)}>重试读取原文</button></p> : <p role="status" className="loading-line"><span className="spinner"/>正在读取资料</p>}
      {error && <p role="alert" className="error">{error}</p>}
      <footer className="reading-footer"><button className={current.completed ? "" : "primary"} disabled={busy || !content} onClick={() => void run(async () => {await put("/reading/" + id, {completed: !current.completed}); await refresh(); notify(current.completed ? "已取消已读标记" : "已标记为已读，计划同步更新");})}><Check size={17}/>{current.completed ? "已读 · 点击撤销" : "标记已读"}</button><div className="row-actions"><button disabled={index <= 0} onClick={() => navigate("reader/" + siblings[index-1].id)}>上一段</button><button disabled={index >= siblings.length-1} onClick={() => navigate("reader/" + siblings[index+1].id)}>下一段</button></div></footer>
      {data.questions.some(q => q.document_id === current.document_id) && <button className="text-button" onClick={() => navigate("practice?doc=" + current.document_id)}>练习这份资料的题目 <ArrowRight size={15}/></button>}
    </article></div>
  </>;
}
