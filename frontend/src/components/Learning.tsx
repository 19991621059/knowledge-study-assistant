import {useEffect, useMemo, useRef, useState} from "react";
import {ArrowLeft, ArrowRight, BookOpen, Check, Circle, Star, Flag, Shuffle, WandSparkles} from "lucide-react";
import {api, post, put, operationId, navigate, route} from "../api";
import {useAction, useApp} from "../context";
import type {AnswerResult, Question, Task} from "../types";
import {ChoiceOptions} from "./ContentBlocks";
import {SourceLinks} from "./Library";

function inFilter(question: Question, filter: string) {
  return filter === "wrong" ? question.latest && !question.latest.correct : filter === "favorite" ? question.favorite : filter === "uncertain" ? question.uncertain : filter === "new" ? !question.latest : true;
}

function practiceParams(filter: string, documentId: string) {
  return new URLSearchParams({filter, doc: documentId}).toString();
}

export function TaskRows({tasks}: {tasks: Task[]}) {
  const {data} = useApp();
  return <div className="task-list">{tasks.map(task => {
    const chunk = data.chunks.find(c => c.id === task.target_id);
    const question = data.questions.find(q => q.id === task.target_id);
    return <button className="task-row" key={task.id} onClick={() => navigate((task.kind === "reading" ? "reader/" : "question/") + task.target_id)}>
      {task.completed ? <Check size={19} className="success"/> : <Circle size={18}/>}<span className="task-kind">{task.kind === "reading" ? "阅读" : "练习"}</span><span className="grow">{chunk?.section || question?.stem || "资料已移除"}</span><span className="task-state">{task.completed ? "已完成" : "开始"}</span><ArrowRight size={16}/>
    </button>;
  })}</div>;
}

export function Today() {
  const {data} = useApp();
  const tasks = data.tasks.filter(t => t.date === data.date);
  const overdue = data.tasks.filter(t => t.date < data.date && !t.completed);
  return <>
    <header className="page-heading"><div><h1>今日学习</h1><p>{data.date} · 阅读和练习按实际记录更新</p></div><button onClick={() => navigate("plan")}>{data.plan ? "调整计划" : "创建计划"}</button></header>
    <div className="stats" aria-label="学习概览"><div><strong>{data.stats.read}<small> / {data.stats.chunks}</small></strong><span>已读片段</span></div><div><strong>{data.stats.practiced}<small> / {data.stats.questions}</small></strong><span>已练题目</span></div><button onClick={() => navigate("practice?filter=wrong")}><strong>{data.stats.wrong}</strong><span>当前错题</span></button><div><strong>{tasks.filter(t => t.completed).length}<small> / {tasks.length}</small></strong><span>今日计划完成</span></div></div>
    <section className="learning-section"><div className="section-heading"><h2>{data.plan?.title || "开始学习"}</h2>{data.plan && <span className="muted">每天{data.plan.daily_target}个学习项</span>}</div>
      {tasks.length ? <TaskRows tasks={tasks}/> : <div className="empty inline"><p>{data.documents.length ? "今日没有安排任务，可以自由阅读或练习。" : "先导入资料，再创建学习计划。"}</p><div className="row-actions"><button className="primary" onClick={() => navigate("library")}>打开资料库</button>{data.questions.length > 0 && <button onClick={() => navigate("practice")}>自由练习</button>}</div></div>}
    </section>
    {overdue.length > 0 && <section className="learning-section"><h2>尚未完成的往日任务 · {overdue.length}</h2><TaskRows tasks={overdue}/></section>}
    {data.stats.wrong > 0 && <div className="review-line"><BookOpen size={20}/><div className="grow"><h2>错题复习</h2><p>答对后移出当前错题，历史作答会保留。</p></div><button onClick={() => navigate("practice?filter=wrong")}>开始复习</button></div>}
  </>;
}

export function Practice() {
  const {data, refresh, notify} = useApp();
  const {busy, error, run} = useAction();
  const params = route().params;
  const [filter, setFilter] = useState(params.get("filter") || "all");
  const [documentId, setDocumentId] = useState(params.get("doc") || "");
  const [generate, setGenerate] = useState(params.get("generate") === "1");
  const [topic, setTopic] = useState("");
  const [count, setCount] = useState(3);
  const pending = useRef<{key: string; id: string} | null>(null);
  useEffect(() => {setFilter(route().params.get("filter") || "all"); setDocumentId(route().params.get("doc") || ""); setGenerate(route().params.get("generate") === "1");}, [window.location.hash]);
  const questions = data.questions.filter(q => (!documentId || q.document_id === documentId) && inFilter(q, filter));
  function changeScope(nextFilter: string, nextDoc: string) {
    setFilter(nextFilter); setDocumentId(nextDoc); navigate("practice?" + practiceParams(nextFilter, nextDoc));
  }
  async function generateQuestions() {
    await run(async () => {
      const selectedDoc = documentId || data.documents[0]?.id;
      if (!selectedDoc) throw new Error("请先导入资料");
      const key = JSON.stringify({document_id: selectedDoc, count, topic});
      if (pending.current?.key !== key) pending.current = {key, id: operationId()};
      const result = await post<{created: number; duplicates: number}>("/questions/generate", {document_id: selectedDoc, count, topic, request_id: pending.current.id});
      pending.current = null; await refresh(); setGenerate(false);
      notify(`已保存${result.created}道AI参考题${result.duplicates ? `，跳过${result.duplicates}道重复题` : ""}；答案和解析待人工核对`);
    });
  }
  return <>
    <header className="page-heading"><div><h1>练习与复习</h1><p>作答、错题和收藏使用同一份学习记录。</p></div><button className="primary" disabled={!data.documents.length} onClick={() => setGenerate(!generate)}><WandSparkles size={17}/>生成练习题</button></header>
    {generate && <form className="form-panel generation-form" onSubmit={e => {e.preventDefault(); void generateQuestions();}}><h2>根据资料生成参考题</h2><div className="form-grid"><label>资料<select value={documentId || data.documents[0]?.id || ""} onChange={e => setDocumentId(e.target.value)}>{data.documents.map(d => <option key={d.id} value={d.id}>{d.title}</option>)}</select></label><label>题数<input type="number" min={1} max={10} value={count} onChange={e => setCount(Number(e.target.value))}/></label></div><label>主题（可选）<input value={topic} onChange={e => setTopic(e.target.value)} placeholder="例如：增量备份与差异备份"/></label><p className="muted small">核对题目格式和逐字出处后保存。AI题仍需核对答案与解析；不作为真题。</p><div className="row-actions"><button className="primary" type="submit" disabled={busy}>{busy ? <><span className="spinner"/>正在生成</> : "生成并保存"}</button><button type="button" disabled={busy} onClick={() => setGenerate(false)}>收起</button></div>{error && <p role="alert" className="error">{error}</p>}</form>}
    <div className="practice-toolbar"><div className="filter-tabs" aria-label="题目筛选">{[["all","全部"],["new","未做"],["wrong","错题"],["favorite","收藏"],["uncertain","不确定"]].map(([key,name]) => <button key={key} aria-pressed={filter === key} className={filter === key ? "selected" : ""} onClick={() => changeScope(key, documentId)}>{name}</button>)}</div><label className="scope-select"><span className="sr-only">练习资料范围</span><select value={documentId} onChange={e => changeScope(filter, e.target.value)}><option value="">全部资料</option>{data.documents.map(d => <option key={d.id} value={d.id}>{d.title}</option>)}</select></label></div>
    <div className="section-heading"><span>{questions.length}道题</span><button disabled={!questions.length} onClick={() => navigate("question/" + questions[Math.floor(Math.random()*questions.length)].id + "?" + practiceParams(filter, documentId))}><Shuffle size={16}/>随机练习</button></div>
    <div className="question-list">{questions.map((question, i) => <button className="question-row" key={question.id} onClick={() => navigate(`question/${question.id}?${practiceParams(filter, documentId)}`)}><span className="question-number">{i+1}</span><div className="grow"><strong>{question.stem}</strong><p>{question.origin === "ai" ? (question.reviewed ? "AI生成 · 已人工核对" : "AI生成 · 待核对") : question.origin === "example" ? "原创示例题" : "导入题 · 请核对来源"}{question.favorite ? " · 已收藏" : ""}</p></div><span className={question.latest ? (question.latest.correct ? "success" : "error") : "muted"}>{question.latest ? (question.latest.correct ? "答对" : "答错") : question.revealed ? "已看答案" : "未作答"}</span><ArrowRight size={16}/></button>)}{!questions.length && <p className="empty">当前范围没有题目，可以切换筛选或根据资料生成练习。</p>}</div>
  </>;
}

export function QuestionPage({id}: {id: string}) {
  const {data, refresh, openAsk} = useApp();
  const {busy, error, run} = useAction();
  const question = data.questions.find(q => q.id === id);
  const [selected, setSelected] = useState<number[]>([]);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [restoreError, setRestoreError] = useState("");
  const [restoreAttempt, setRestoreAttempt] = useState(0);
  const pending = useRef<{key: string; id: string} | null>(null);
  const doc = data.documents.find(d => d.id === question?.document_id);
  useEffect(() => {
    let alive = true;
    setSelected(question?.draft || []); setResult(null); setLoading(true); setRestoreError(""); pending.current = null;
    api<AnswerResult | null>("/questions/" + id + "/result").then(value => {if (alive) {setResult(value); if (value) setSelected(value.selected);}}).catch(e => {if (alive) setRestoreError(e.message);}).finally(() => {if (alive) setLoading(false);});
    return () => {alive = false;};
  }, [id, restoreAttempt]);
  const params = route().params;
  const filter = params.get("filter") || "all";
  const documentId = params.has("doc") ? params.get("doc") || "" : question?.document_id || "";
  // 已答对的当前题留到离开页面，下一题仍从所选复习范围中取。
  const ordered = data.questions.filter(q => (!documentId || q.document_id === documentId) && (q.id === id || inFilter(q, filter)));
  const index = ordered.findIndex(q => q.id === id);
  if (!question) return <p className="empty">题目不存在，请返回题库。</p>;
  async function submit(mode: "answer" | "reveal") {
    await run(async () => {
      const payload = {selected: mode === "answer" ? selected : [], mode};
      const key = JSON.stringify(payload);
      if (pending.current?.key !== key) pending.current = {key, id: operationId()};
      const value = await post<AnswerResult>("/questions/" + id + "/answer", {...payload, request_id: pending.current.id});
      setResult(value); pending.current = null; await refresh();
    });
  }
  async function mark(field: "favorite" | "uncertain", current: number) {
    await run(async () => {await put("/questions/" + id + "/marks", {[field]: !current}); await refresh();});
  }
  return <section className="question-page"><button className="text-button" onClick={() => navigate("practice?" + practiceParams(filter, documentId))}><ArrowLeft size={17}/>返回练习列表</button><div className="question-meta"><span>{doc?.title} · 第{index+1}题 / {ordered.length} · {question.multiple ? "多选题" : "单选题"}</span><span>{question.origin === "ai" ? `AI参考题 · ${question.reviewed ? "已人工核对" : "待核对"}` : question.origin === "example" ? "原创示例题" : "导入参考题"}</span></div><h1>{question.stem}</h1>
    {restoreError && <p role="alert" className="error">读取已保存作答失败：{restoreError} <button onClick={() => setRestoreAttempt(value => value + 1)}>重试读取</button></p>}
    <ChoiceOptions options={Object.fromEntries(question.options.map((text, i) => [String(i), text]))} selected={selected.map(String)} multiple={question.multiple} disabled={busy || !!result || loading || !!restoreError} onSelect={async values => {const next = values.map(Number); await put("/questions/" + id + "/draft", {selected: next}); setSelected(next);}}/>
    {error && <p role="alert" className="error">{error}</p>}
    {!result ? <div className="question-actions"><button className="primary" disabled={!selected.length || busy || loading || !!restoreError} onClick={() => void submit("answer")}>{busy ? "正在保存" : "提交答案"}</button><button disabled={busy || loading || !!restoreError} onClick={() => void submit("reveal")}>查看答案</button><p className="muted small">直接查看答案不计为完成作答。</p></div> : <div className="answer-result"><h2 className={result.mode === "reveal" ? "" : result.correct ? "success" : "error"}>{result.mode === "reveal" ? "已查看答案" : result.correct ? "答对 · 已保存" : "答错 · 已加入错题"}</h2><p>参考答案：{result.answer.map(i => String.fromCharCode(65+i)).join("、")}</p><p>{result.explanation}</p>{result.reference_only && <p className="muted small">这是待核对的AI参考答案，请结合原文检查。</p>}<SourceLinks sources={result.sources}/><div className="row-actions"><button disabled={busy} onClick={() => void run(async () => {await put("/questions/" + id + "/draft", {selected: []}); setResult(null); setSelected([]);})}>再次练习</button><button className="primary" disabled={index >= ordered.length-1} onClick={() => navigate("question/" + ordered[index+1].id + "?" + practiceParams(filter, documentId))}>下一题 <ArrowRight size={16}/></button></div></div>}
    <footer className="question-tools"><button aria-pressed={!!question.favorite} disabled={busy} onClick={() => void mark("favorite", question.favorite)}><Star size={16}/>{question.favorite ? "取消收藏" : "收藏题目"}</button><button aria-pressed={!!question.uncertain} disabled={busy} onClick={() => void mark("uncertain", question.uncertain)}><Flag size={16}/>{question.uncertain ? "取消不确定" : "标记不确定"}</button>{result && <button onClick={() => openAsk(`请根据资料解释这道题：${question.stem}`, question.document_id)}>追问题目</button>}{question.origin === "ai" && !question.reviewed && result && <button disabled={busy} onClick={() => void run(async () => {await put("/questions/" + id + "/marks", {reviewed: true}); await refresh();})}>我已核对题目</button>}</footer>
  </section>;
}

export function PlanPage() {
  const {data, refresh, notify} = useApp();
  const {busy, error, run} = useAction();
  const [title, setTitle] = useState("我的学习计划");
  const [daily, setDaily] = useState(5);
  const [documentId, setDocumentId] = useState("");
  const pending = useRef<{key: string; id: string} | null>(null);
  const groups = useMemo(() => [...new Set(data.tasks.map(t => t.date))], [data.tasks]);
  async function create() {
    await run(async () => {
      const payload = {title, daily_target: daily, document_id: documentId || null};
      const key = JSON.stringify(payload);
      if (pending.current?.key !== key) pending.current = {key, id: operationId()};
      const result = await post<{days: number; tasks: number; end_date: string}>("/plans", {...payload, request_id: pending.current.id});
      pending.current = null; await refresh(); notify(`已安排${result.tasks}个学习项，预计${result.days}天完成`);
    });
  }
  return <>
    <header className="page-heading"><div><h1>学习计划</h1><p>按未完成的原文片段和未作答题目排期，完成状态由实际学习更新。</p></div></header>
    <form className="form-panel plan-form" onSubmit={e => {e.preventDefault(); void create();}}><h2>{data.plan ? "调整剩余内容" : "创建学习计划"}</h2><div className="form-grid"><label>计划名称<input required maxLength={100} value={title} onChange={e => setTitle(e.target.value)}/></label><label>每天学习项数<input type="number" min={1} max={100} required value={daily} onChange={e => setDaily(Number(e.target.value))}/></label></div><label>资料范围<select value={documentId} onChange={e => setDocumentId(e.target.value)}><option value="">全部资料</option>{data.documents.map(d => <option key={d.id} value={d.id}>{d.title}</option>)}</select></label><p className="muted small">一个学习项是一段阅读或一道练习。标记已读、提交答案后同步完成；错题另行复习。调整计划保留已有记录。</p><button className="primary" type="submit" disabled={busy || !data.documents.length}>{busy ? "正在安排" : data.plan ? "重新安排剩余内容" : "生成学习计划"}</button>{error && <p role="alert" className="error">{error}</p>}</form>
    {data.plan && <section className="plan-schedule"><div className="section-heading"><h2>{data.plan.title}</h2><span className="muted">{data.tasks.filter(t => t.completed).length} / {data.tasks.length}项已完成</span></div>{groups.map(date => <details key={date} open={date === data.date}><summary>{date}{date === data.date ? " · 今天" : ""}<span>{data.tasks.filter(t => t.date === date && t.completed).length} / {data.tasks.filter(t => t.date === date).length}完成</span></summary><TaskRows tasks={data.tasks.filter(t => t.date === date)}/></details>)}</section>}
  </>;
}
