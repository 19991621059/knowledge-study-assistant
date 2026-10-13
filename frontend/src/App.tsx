import {useEffect, useState} from "react";
import {BookOpen, CalendarDays, ClipboardList, Library as LibraryIcon, LogOut, MessageSquare, RefreshCw, Settings as SettingsIcon, X} from "lucide-react";
import {api, post, navigate, route} from "./api";
import {AppContext} from "./context";
import {Library, Reader} from "./components/Library";
import {Today, Practice, QuestionPage, PlanPage} from "./components/Learning";
import {Settings} from "./components/Settings";
import {ChatDialog} from "./components/Chat";
import type {AppState} from "./types";

export default function App() {
  const [session, setSession] = useState<{authenticated: boolean; initialized: boolean} | null>(null);
  const [data, setData] = useState<AppState | null>(null);
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [logging, setLogging] = useState(false);
  const [path, setPath] = useState(route().path);
  const [notice, setNotice] = useState<{message: string; error: boolean} | null>(null);
  const [ask, setAsk] = useState<{draft: string; documentId: string} | null>(null);
  const [font, setFont] = useState(() => {
    const saved = Number(localStorage.getItem("study-font") || "100");
    return [100, 115, 130].includes(saved) ? saved : 100;
  });
  const [readyError, setReadyError] = useState("");
  function notify(message: string, error = false) {setNotice({message, error});}
  async function refresh() {const value = await api<AppState>("/state"); setData(value); setReadyError("");}
  useEffect(() => {
    const change = () => {setPath(route().path); window.scrollTo(0, 0);};
    const expired = () => {setSession({authenticated: false, initialized: true}); setData(null); setAsk(null);};
    window.addEventListener("hashchange", change); window.addEventListener("session-expired", expired);
    api<{authenticated: boolean; initialized: boolean}>("/session").then(setSession).catch(e => setReadyError(e.message));
    return () => {window.removeEventListener("hashchange", change); window.removeEventListener("session-expired", expired);};
  }, []);
  useEffect(() => {
    if (!session?.authenticated) return;
    void refresh().catch(e => setReadyError(e.message));
    const timer = setInterval(() => {if (!document.hidden) void refresh().catch(() => {});}, 30000);
    return () => clearInterval(timer);
  }, [session?.authenticated]);
  useEffect(() => {localStorage.setItem("study-font", String(font)); document.documentElement.style.fontSize = font + "%";}, [font]);
  async function login() {
    setLogging(true); setLoginError("");
    try {await post("/login", {password}); setPassword(""); setSession({authenticated: true, initialized: true});}
    catch (e) {setLoginError(e instanceof Error ? e.message : "登录失败，请重试");}
    finally {setLogging(false);}
  }
  if (!session) return <main className="login-page"><h1>资料学习助手</h1>{readyError ? <p className="error" role="alert">{readyError}</p> : <p role="status"><span className="spinner"/>正在连接</p>}</main>;
  if (!session.authenticated) return <main className="login-page"><div className="login-brand"><BookOpen size={32}/><h1>资料学习助手</h1></div><p>导入自己的资料，连接自己的模型。</p>{session.initialized ? <form onSubmit={e => {e.preventDefault(); void login();}}><label>访问密码<input type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)}/></label><button className="primary" type="submit" disabled={logging}>{logging ? "正在登录" : "进入学习"}</button>{loginError && <p role="alert" className="error">{loginError}</p>}</form> : <div className="form-panel"><p>还未设置访问密码。请按 README 在服务端执行初始化，再启动应用。</p><code>python -m study_assistant init</code></div>}<p className="muted small">资料和学习记录保存在这个自部署服务中。</p></main>;
  if (!data) return <main className="login-page"><h1>资料学习助手</h1>{readyError ? <><p role="alert" className="error">{readyError}</p><button onClick={() => void refresh().catch(e => setReadyError(e.message))}>重试读取</button></> : <p role="status"><span className="spinner"/>正在读取学习记录</p>}</main>;
  const current = path.startsWith("reader/") ? "library" : path.startsWith("question/") ? "practice" : path;
  const links = [{id: "today", text: "今日学习", icon: CalendarDays}, {id: "library", text: "资料库", icon: LibraryIcon}, {id: "practice", text: "练习复习", icon: ClipboardList}, {id: "plan", text: "学习计划", icon: BookOpen}, {id: "settings", text: "设置", icon: SettingsIcon}];
  return <AppContext.Provider value={{data, refresh, notify, openAsk: (draft = "", documentId = "") => setAsk({draft, documentId})}}><a className="skip-link" href="#main-content" onClick={e => {e.preventDefault(); document.getElementById("main-content")?.focus();}}>跳到正文</a><div className="app-shell"><aside className="sidebar"><a className="brand" href="#today"><BookOpen size={25}/><span>资料学习助手</span></a><nav aria-label="主要导航">{links.map(link => <button key={link.id} className={current === link.id ? "selected" : ""} aria-current={current === link.id ? "page" : undefined} onClick={() => navigate(link.id)}><link.icon size={19}/><span>{link.text}</span></button>)}</nav><div className="sidebar-bottom"><span className="muted small">个人资料库 · 自部署</span><button className="text-button" onClick={() => void post("/logout").then(() => {setSession({authenticated: false, initialized: true}); setData(null); setAsk(null);}).catch(e => notify(e.message, true))}><LogOut size={17}/>退出登录</button></div></aside><div className="workspace"><header className="utility-bar"><span>{data.model.configured ? "模型已配置" : "模型待配置"}</span><div className="row-actions"><label className="font-control">字号<select aria-label="阅读字号" value={font} onChange={e => setFont(Number(e.target.value))}><option value={100}>标准</option><option value={115}>较大</option><option value={130}>大</option></select></label><button className="icon-button" aria-label="刷新学习记录" onClick={() => void refresh().then(() => notify("记录已刷新")).catch(e => notify(e.message, true))}><RefreshCw size={17}/></button></div></header><main id="main-content" tabIndex={-1}>
    {path === "today" ? <Today/> : path === "library" ? <Library/> : path === "practice" ? <Practice/> : path.startsWith("reader/") ? <Reader key={path} id={path.slice(7)}/> : path.startsWith("question/") ? <QuestionPage key={path} id={path.slice(9)}/> : path === "plan" ? <PlanPage/> : path === "settings" ? <Settings/> : <Today/>}
  </main></div></div>{notice && <div className={"notice " + (notice.error ? "error" : "")} role={notice.error ? "alert" : "status"}><span>{notice.message}</span><button className="icon-button" aria-label="关闭提示" onClick={() => setNotice(null)}><X size={17}/></button></div>}<button className="ask-launcher" onClick={() => setAsk({draft: "", documentId: ""})}><MessageSquare size={18}/><span>提问资料</span></button>{ask && <ChatDialog draft={ask.draft} documentId={ask.documentId} close={() => setAsk(null)}/>}</AppContext.Provider>;
}
