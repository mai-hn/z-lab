"use client";

import { useEffect, useMemo, useState } from "react";
import { ModelIcon, PlusIcon, RefreshIcon, TrashIcon } from "@/components/icons";
import { api } from "@/lib/api";

type Credentials = { base_url: string; api_key: string };
type Message = { role: "system" | "user" | "assistant"; content: string };
type HistoryItem = { id: string; model: string; prompt: string; result: string; createdAt: string };
type Parameters = { temperature: number; max_tokens: number; top_p: number; frequency_penalty: number };

const CREDENTIALS_KEY = "z-lab:model-credentials";
const HISTORY_KEY = "z-lab:model-history";
const defaults: Credentials = { base_url: "https://api.openai.com/v1", api_key: "" };
const defaultParameters: Parameters = { temperature: 0.7, max_tokens: 2048, top_p: 1, frequency_penalty: 0 };

export default function ModelsPage() {
  const [tab, setTab] = useState("models");
  const [credentials, setCredentials] = useState<Credentials>(defaults);
  const [models, setModels] = useState<string[]>([]);
  const [selected, setSelected] = useState("");
  const [comparison, setComparison] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<HistoryItem[]>([]);

  useEffect(() => {
    const saved = window.localStorage.getItem(CREDENTIALS_KEY);
    const savedHistory = window.localStorage.getItem(HISTORY_KEY);
    if (saved) setCredentials(JSON.parse(saved));
    if (savedHistory) setHistory(JSON.parse(savedHistory));
  }, []);

  function saveCredentials(next: Credentials) {
    setCredentials(next);
    window.localStorage.setItem(CREDENTIALS_KEY, JSON.stringify(next));
  }

  function addHistory(item: Omit<HistoryItem, "id" | "createdAt">) {
    const next = [{ ...item, id: crypto.randomUUID(), createdAt: new Date().toISOString() }, ...history].slice(0, 50);
    setHistory(next);
    window.localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
  }

  async function loadModels() {
    setBusy(true);
    setMessage("");
    try {
      const result = await api<{ models: string[] }>("/api/models/list", { method: "POST", body: JSON.stringify(credentials) });
      setModels(result.models);
      setSelected((current) => current || result.models[0] || "");
      setMessage(`已发现 ${result.models.length} 个模型。`);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const filtered = useMemo(() => models.filter((model) => model.toLowerCase().includes(query.toLowerCase())), [models, query]);

  return (
    <div className="workspace-page accent-green">
      <div className="workspace-header">
        <div className="workspace-title">
          <span className="workspace-icon"><ModelIcon size={34} /></span>
          <div><span className="eyebrow">PROJECT 03 / AI TOOLS</span><h1>AI Model Checker</h1></div>
        </div>
        <div className="workspace-status"><span className="status-dot" /> OPENAI-COMPATIBLE · LOCAL CREDENTIALS</div>
      </div>

      <nav className="tabs">
        {[["models", "模型发现"], ["single", "单次生成"], ["chat", "多轮对话"], ["compare", "模型对比"], ["history", "历史"]].map(([id, label]) => (
          <button key={id} className={`tab ${tab === id ? "active" : ""}`} onClick={() => setTab(id)}>{label}</button>
        ))}
      </nav>

      {message && <p className={`notice ${message.startsWith("已发现") ? "success" : message.includes("错误") ? "error" : ""}`}>{message}</p>}

      <section className="credential-bar">
        <div className="field"><label>API BASE URL</label><input className="input mono" value={credentials.base_url} onChange={(event) => saveCredentials({ ...credentials, base_url: event.target.value })} /></div>
        <div className="field"><label>API KEY · 仅保存在浏览器</label><input className="input" type="password" placeholder="sk-••••••••" value={credentials.api_key} onChange={(event) => saveCredentials({ ...credentials, api_key: event.target.value })} /></div>
        <button className="button button-green" disabled={busy || !credentials.api_key} onClick={() => void loadModels()}><RefreshIcon /> {busy ? "连接中…" : "读取模型"}</button>
      </section>

      {tab === "models" && (
        <section className="panel">
          <header className="panel-header">
            <div><h2>可用模型</h2><small className="muted">GET /models 返回的完整列表。</small></div>
            <input className="input model-search" placeholder="搜索模型…" value={query} onChange={(event) => setQuery(event.target.value)} />
          </header>
          <div className="model-grid">
            {filtered.map((model) => (
              <button className={`model-card ${selected === model ? "selected" : ""}`} key={model} onClick={() => { setSelected(model); setTab("single"); }}>
                <ModelIcon size={24} /><b>{model}</b><span>选择并测试 →</span>
              </button>
            ))}
          </div>
          {!models.length && <div className="empty-state"><div><strong>先连接一个 OpenAI 兼容服务</strong>凭据仅保存在 localStorage，Python API 只做代理请求。</div></div>}
        </section>
      )}

      {tab === "single" && <GenerationPanel credentials={credentials} models={models} selected={selected} setSelected={setSelected} onHistory={addHistory} onError={setMessage} />}
      {tab === "chat" && <ChatPanel credentials={credentials} models={models} selected={selected} setSelected={setSelected} onError={setMessage} />}
      {tab === "compare" && <ComparePanel credentials={credentials} models={models} comparison={comparison} setComparison={setComparison} onHistory={addHistory} onError={setMessage} />}
      {tab === "history" && <HistoryPanel history={history} onClear={() => { setHistory([]); window.localStorage.removeItem(HISTORY_KEY); }} />}
    </div>
  );
}

function ModelSelect({ models, value, onChange }: { models: string[]; value: string; onChange: (value: string) => void }) {
  return <select className="select" value={value} onChange={(event) => onChange(event.target.value)}><option value="">选择模型</option>{models.map((model) => <option value={model} key={model}>{model}</option>)}</select>;
}

function GenerationPanel({ credentials, models, selected, setSelected, onHistory, onError }: { credentials: Credentials; models: string[]; selected: string; setSelected: (value: string) => void; onHistory: (item: Omit<HistoryItem, "id" | "createdAt">) => void; onError: (value: string) => void }) {
  const [prompt, setPrompt] = useState("用三句话解释为什么清晰的工具比功能繁多的工具更好。");
  const [system, setSystem] = useState("你是一名简洁、准确的技术写作者。");
  const [result, setResult] = useState("");
  const [params, setParams] = useState(defaultParameters);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true); setResult("");
    try {
      const content = await streamChat({ ...credentials, model: selected, prompt, system_prompt: system, ...params }, setResult);
      onHistory({ model: selected, prompt, result: content });
    } catch (error) {
      onError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="model-workbench">
      <section className="panel generator-form">
        <header className="panel-header"><h2>请求</h2><span className="badge">STREAM</span></header>
        <div className="panel-body">
          <Field label="模型"><ModelSelect models={models} value={selected} onChange={setSelected} /></Field>
          <Field label="系统提示词"><textarea className="textarea small-textarea" value={system} onChange={(event) => setSystem(event.target.value)} /></Field>
          <Field label="用户提示词"><textarea className="textarea" value={prompt} onChange={(event) => setPrompt(event.target.value)} /></Field>
          <ParameterGrid value={params} onChange={setParams} />
          <button className="button button-green" disabled={busy || !selected || !prompt || !credentials.api_key} onClick={() => void run()}>{busy ? "生成中…" : "开始生成 →"}</button>
        </div>
      </section>
      <section className="panel">
        <header className="panel-header"><h2>实时响应</h2>{busy && <span className="badge success pulse">GENERATING</span>}</header>
        <div className={`model-output ${result ? "" : "muted"}`}>{result || "选择模型并发送请求，流式结果会立即显示在这里。"}</div>
      </section>
    </div>
  );
}

function ChatPanel({ credentials, models, selected, setSelected, onError }: { credentials: Credentials; models: string[]; selected: string; setSelected: (value: string) => void; onError: (value: string) => void }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  async function send() {
    if (!input.trim()) return;
    const next: Message[] = [...messages, { role: "user", content: input.trim() }];
    setMessages(next); setInput(""); setBusy(true);
    try {
      let current = "";
      await streamChat({ ...credentials, model: selected, prompt: input, messages: next, ...defaultParameters }, (value) => {
        current = value;
        setMessages([...next, { role: "assistant", content: value }]);
      });
      if (!current) setMessages(next);
    } catch (error) {
      onError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return <section className="panel chat-panel"><header className="panel-header"><div className="chat-model"><span className="field-label">MODEL</span><ModelSelect models={models} value={selected} onChange={setSelected} /></div><button className="button button-quiet" onClick={() => setMessages([])}>清空对话</button></header><div className="chat-messages">{messages.map((item, index) => <div className={`chat-message ${item.role}`} key={`${index}-${item.role}`}><b>{item.role === "user" ? "YOU" : "MODEL"}</b><p>{item.content}</p></div>)}{!messages.length && <div className="empty-state"><div><strong>开始一段模型对话</strong>上下文会随每次请求一起发送，但不会保存在服务器。</div></div>}</div><div className="chat-compose"><textarea className="textarea" placeholder="输入消息；⌘/Ctrl + Enter 发送" value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") void send(); }} /><button className="button button-green" disabled={busy || !selected || !input || !credentials.api_key} onClick={() => void send()}>{busy ? "…" : "发送 →"}</button></div></section>;
}

function ComparePanel({ credentials, models, comparison, setComparison, onHistory, onError }: { credentials: Credentials; models: string[]; comparison: string[]; setComparison: (value: string[]) => void; onHistory: (item: Omit<HistoryItem, "id" | "createdAt">) => void; onError: (value: string) => void }) {
  const [prompt, setPrompt] = useState("解释什么是幂等性，并给出一个 API 设计示例。");
  const [results, setResults] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  function toggle(model: string) {
    setComparison(comparison.includes(model) ? comparison.filter((item) => item !== model) : comparison.length < 3 ? [...comparison, model] : comparison);
  }

  async function run() {
    setBusy(true); setResults({});
    try {
      await Promise.all(comparison.map(async (model) => {
        const content = await streamChat({ ...credentials, model, prompt, ...defaultParameters }, (value) => setResults((current) => ({ ...current, [model]: value })));
        onHistory({ model, prompt, result: content });
      }));
    } catch (error) {
      onError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return <><section className="panel compare-config"><header className="panel-header"><div><h2>并行模型对比</h2><small className="muted">最多选择 3 个模型；请求由 Python API 并行代理。</small></div><span className="badge">{comparison.length} / 3</span></header><div className="panel-body"><div className="compare-models">{models.map((model) => <button key={model} className={`badge ${comparison.includes(model) ? "success" : ""}`} onClick={() => toggle(model)}>{comparison.includes(model) ? "✓ " : "+ "}{model}</button>)}</div><textarea className="textarea" value={prompt} onChange={(event) => setPrompt(event.target.value)} /><button className="button button-green" disabled={busy || !comparison.length || !credentials.api_key} onClick={() => void run()}>{busy ? "对比中…" : "同时运行"}</button></div></section><div className="comparison-grid">{comparison.map((model) => <section className="panel" key={model}><header className="panel-header"><h2>{model}</h2>{busy && <span className="badge success">LIVE</span>}</header><div className={`model-output compact ${results[model] ? "" : "muted"}`}>{results[model] || "等待运行…"}</div></section>)}</div></>;
}

function HistoryPanel({ history, onClear }: { history: HistoryItem[]; onClear: () => void }) {
  return <section className="panel"><header className="panel-header"><div><h2>本地测试历史</h2><small className="muted">只保存在当前浏览器，最多 50 条。</small></div><button className="button button-quiet" onClick={onClear}><TrashIcon /> 清空</button></header><div className="history-list">{history.map((item) => <details key={item.id}><summary><span className="badge">{item.model}</span><b>{item.prompt.slice(0, 80)}</b><time>{new Date(item.createdAt).toLocaleString("zh-CN")}</time></summary><div><p className="mono">{item.prompt}</p><pre>{item.result}</pre></div></details>)}{!history.length && <div className="empty-state"><div><strong>暂无历史</strong>单次生成和模型对比的结果会出现在这里。</div></div>}</div></section>;
}

function ParameterGrid({ value, onChange }: { value: Parameters; onChange: (value: Parameters) => void }) {
  return <details className="parameter-box"><summary>高级参数</summary><div className="form-grid"><Field label={`TEMPERATURE · ${value.temperature}`}><input type="range" min="0" max="2" step="0.1" value={value.temperature} onChange={(event) => onChange({ ...value, temperature: Number(event.target.value) })} /></Field><Field label="MAX TOKENS"><input className="input" type="number" value={value.max_tokens} onChange={(event) => onChange({ ...value, max_tokens: Number(event.target.value) })} /></Field><Field label={`TOP P · ${value.top_p}`}><input type="range" min="0" max="1" step="0.05" value={value.top_p} onChange={(event) => onChange({ ...value, top_p: Number(event.target.value) })} /></Field><Field label="FREQUENCY PENALTY"><input className="input" type="number" min="-2" max="2" step="0.1" value={value.frequency_penalty} onChange={(event) => onChange({ ...value, frequency_penalty: Number(event.target.value) })} /></Field></div></details>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="field"><label>{label}</label>{children}</div>;
}

async function streamChat(payload: Record<string, unknown>, onUpdate: (value: string) => void): Promise<string> {
  const response = await fetch("/api/models/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...payload, stream: true }) });
  if (!response.ok || !response.body) {
    const data = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(data.detail || response.statusText);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let complete = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const event of events) {
      if (event.startsWith("event: error")) {
        const dataLine = event.split("\n").find((line) => line.startsWith("data:"));
        const detail = dataLine ? JSON.parse(dataLine.slice(5)).detail : "模型请求失败";
        throw new Error(detail);
      }
      const dataLine = event.split("\n").find((line) => line.startsWith("data:"));
      if (!dataLine) continue;
      const data = dataLine.slice(5).trim();
      if (data === "[DONE]") continue;
      try {
        complete += JSON.parse(data).choices?.[0]?.delta?.content ?? "";
        onUpdate(complete);
      } catch {
        // Ignore provider heartbeat or non-JSON lines.
      }
    }
  }
  return complete;
}
