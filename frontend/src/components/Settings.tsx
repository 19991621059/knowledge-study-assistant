import {useEffect, useRef, useState} from "react";
import {Download, KeyRound, Upload} from "lucide-react";
import {api, post, put} from "../api";
import {useApp, useAction} from "../context";
export function Settings() {
  const {data, refresh, notify} = useApp();
  const {busy, error, run} = useAction();
  const [address, setAddress] = useState(data.model.base_url);
  const [model, setModel] = useState(data.model.model);
  const [key, setKey] = useState("");
  const [noKey, setNoKey] = useState(data.model.allow_no_key);
  const [jsonMode, setJsonMode] = useState(data.model.json_mode);
  const [clearKey, setClearKey] = useState(false);
  const restoreInput = useRef<HTMLInputElement>(null);
  useEffect(() => {setAddress(data.model.base_url); setModel(data.model.model); setNoKey(data.model.allow_no_key); setJsonMode(data.model.json_mode);}, [data.model.base_url, data.model.model]);
  async function save() {
    await run(async () => {
      await put("/model", {base_url: address, model, api_key: key, allow_no_key: noKey, json_mode: jsonMode, clear_key: clearKey});
      setKey(""); setClearKey(false); await refresh(); notify("模型配置已保存，密钥仅由服务端加密保存");
    });
  }
  async function restore(file?: File) {
    if (!file) return;
    await run(async () => {const body = new FormData(); body.append("file", file); await api("/backup/restore", {method: "POST", body}); await refresh(); notify("资料与学习记录已恢复；模型密钥需要单独配置");});
    if (restoreInput.current) restoreInput.current.value = "";
  }
  return <>
    <header className="page-heading"><div><h1>设置</h1><p>使用自己的模型服务，管理自己的资料与记录。</p></div></header>
    <form className="form-panel model-form" onSubmit={e => {e.preventDefault(); void save();}}><h2><KeyRound size={20}/>模型配置</h2><label>模型接口地址<input type="url" required placeholder="https://服务商地址/v1" value={address} onChange={e => setAddress(e.target.value)}/></label><p className="muted small">填写基础地址，系统会追加 /chat/completions。兼容 OpenAI Chat Completions；本地服务支持 localhost、127.0.0.1 与 host.docker.internal。</p><label>模型名称<input required maxLength={200} placeholder="按服务商提供的模型标识填写" value={model} onChange={e => setModel(e.target.value)}/></label><label>API 密钥<input type="password" autoComplete="new-password" placeholder={data.model.has_key ? "已保存密钥，留空保持现有值" : "填写自己的 API 密钥"} value={key} onChange={e => setKey(e.target.value)}/></label><div className="checkboxes"><label><input type="checkbox" checked={noKey} onChange={e => setNoKey(e.target.checked)}/>本地模型服务无需 API 密钥</label><label><input type="checkbox" checked={jsonMode} onChange={e => setJsonMode(e.target.checked)}/>服务商支持 JSON 模式（出题时启用）</label>{data.model.has_key && <label><input type="checkbox" checked={clearKey} onChange={e => setClearKey(e.target.checked)}/>清除旧密钥</label>}</div><div className="row-actions"><button className="primary" type="submit" disabled={busy}>{busy ? "正在处理" : "保存模型配置"}</button><button type="button" disabled={busy || !data.model.configured} onClick={() => void run(async () => {await post("/model/test"); notify("连接成功，已收到模型的真实回复");})}>测试已保存的连接</button></div>{error && <p role="alert" className="error">{error}</p>}<p className="muted small">资料片段和问题会发送给你配置的模型服务。密钥不会回填页面，也不会写入可下载的学习备份。</p></form>
    <section className="form-panel"><h2>资料与学习记录备份</h2><p>备份包含原文件、题目、阅读位置、作答、收藏、计划和问答；不包含访问密码、登录会话或模型密钥。请妥善保存。</p><div className="row-actions"><a className="button-link" href="/api/backup" download><Download size={17}/>下载学习备份</a><button disabled={busy || !!data.documents.length} onClick={() => restoreInput.current?.click()}><Upload size={17}/>恢复到空资料库</button></div><p className="muted small">为保护当前资料，只允许恢复到空资料库；迁移步骤见 README。</p><input ref={restoreInput} className="sr-only" type="file" accept=".json" aria-label="选择学习备份" onChange={e => void restore(e.target.files?.[0])}/></section>
    <section className="form-panel"><h2>当前版本与范围</h2><p>0.1.0 · 单人自部署网页应用。原生安卓与桌面端、短信登录、原项目云服务和自动更新未接入这个独立服务。</p><p>关键词检索不等于全文语义理解；引用定位核对不等于答案正确性审核。扫描 PDF、图片理解、正式考试和多人权限管理未支持。</p><a href="https://github.com/19991621059/knowledge-study-assistant" target="_blank" rel="noreferrer">查看安装文档与源代码</a></section>
  </>;
}
