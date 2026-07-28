"use client";

import { useCallback, useEffect, useState } from "react";
import { PlusIcon, RefreshIcon, RouteIcon, SettingsIcon, TrashIcon } from "@/components/icons";
import { api, formatDate } from "@/lib/api";

type Provider = {
  id: number;
  name: string;
  kind: string;
  endpoint: string;
  priority: number;
  weight: number;
  enabled: boolean;
  timeout_seconds: number;
  last_status?: string;
  last_latency_ms?: number;
  last_error?: string;
  quota_exceeded?: boolean;
};
type ProviderKind = { kind: string; label: string; default_endpoint?: string; fields?: string[] };
type Dashboard = {
  providers: { total: number; enabled: number; healthy: number; quota_exceeded: number };
  requests: { total?: number; last_24h?: number; success_24h?: number; failed_24h?: number; avg_latency_24h?: number };
};
type Log = {
  id: number;
  request_id: string;
  route: string;
  provider?: string;
  status: string;
  latency_ms?: number;
  error?: string;
  created_at: string;
};
type RouterSettings = { routing_mode: string; fallback_enabled: boolean; downstream_key_hint: string; downstream_key: string };

const BASE = "/api/router";
const API = `${BASE}/api`;

export default function RouterPage() {
  const [tab, setTab] = useState("overview");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [kinds, setKinds] = useState<ProviderKind[]>([]);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [logs, setLogs] = useState<Log[]>([]);
  const [settings, setSettings] = useState<RouterSettings | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [providerModal, setProviderModal] = useState<Provider | null | "new">(null);

  const refresh = useCallback(async () => {
    try {
      const [providerData, kindData, dashData, logData, settingsData] = await Promise.all([
        api<Provider[]>(`${API}/providers`),
        api<ProviderKind[]>(`${API}/upstream-kinds`),
        api<Dashboard>(`${API}/dashboard`),
        api<Log[]>(`${API}/logs?limit=50`),
        api<RouterSettings>(`${API}/settings`),
      ]);
      setProviders(providerData);
      setKinds(kindData);
      setDashboard(dashData);
      setLogs(logData);
      setSettings(settingsData);
      setMessage("");
    } catch (error) {
      setMessage((error as Error).message);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function checkAll() {
    setBusy(true);
    try {
      const result = await api<{ healthy: number; unhealthy: number }>(`${API}/providers/check`, { method: "POST" });
      setMessage(`检查完成：${result.healthy} 个健康，${result.unhealthy} 个异常。`);
      await refresh();
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function deleteProvider(provider: Provider) {
    if (!window.confirm(`删除路由“${provider.name}”？`)) return;
    try {
      await api(`${API}/providers/${provider.id}`, { method: "DELETE" });
      await refresh();
    } catch (error) {
      setMessage((error as Error).message);
    }
  }

  const requestStats = dashboard?.requests ?? {};
  const successRate = requestStats.last_24h
    ? ((requestStats.success_24h ?? 0) / requestStats.last_24h) * 100
    : 0;

  return (
    <div className="workspace-page accent-purple">
      <div className="workspace-header">
        <div className="workspace-title">
          <span className="workspace-icon"><RouteIcon size={34} /></span>
          <div><span className="eyebrow">PROJECT 02 / ROUTING</span><h1>DeepRouter</h1></div>
        </div>
        <div className="workspace-status"><span className="status-dot" /> DEEPL-COMPATIBLE · ONLINE</div>
      </div>

      <nav className="tabs">
        {[["overview", "概览"], ["providers", "上游路由"], ["playground", "翻译测试"], ["logs", "请求日志"], ["settings", "设置"]].map(([id, label]) => (
          <button key={id} className={`tab ${tab === id ? "active" : ""}`} onClick={() => setTab(id)}>{label}</button>
        ))}
      </nav>

      {message && <p className={`notice ${message.includes("完成") ? "success" : ""}`}>{message}</p>}

      {tab === "overview" && (
        <>
          <div className="stats-grid">
            <Stat label="PROVIDERS" value={String(dashboard?.providers.total ?? 0)} note={`${dashboard?.providers.enabled ?? 0} 个已启用`} />
            <Stat label="HEALTHY" value={String(dashboard?.providers.healthy ?? 0)} note="最近一次检查通过" />
            <Stat label="SUCCESS RATE" value={`${successRate.toFixed(1)}%`} note={`${requestStats.last_24h ?? 0} 个 24h 请求`} />
            <Stat label="AVG LATENCY" value={`${Math.round(requestStats.avg_latency_24h ?? 0)} ms`} note="最近 24 小时" />
          </div>
          <div className="split-view">
            <section className="panel">
              <header className="panel-header"><h2>路由策略</h2><span className="badge success">ACTIVE</span></header>
              <div className="panel-body strategy-diagram">
                <div><b>01</b><span>最低优先级组</span></div><i>→</i>
                <div><b>02</b><span>组内加权轮询</span></div><i>→</i>
                <div><b>03</b><span>失败自动回退</span></div>
              </div>
            </section>
            <section className="panel">
              <header className="panel-header"><h2>上游状态</h2><button className="button button-quiet" disabled={busy} onClick={() => void checkAll()}><RefreshIcon /> {busy ? "检查中…" : "全部检查"}</button></header>
              <div className="provider-health-list">
                {providers.slice(0, 6).map((provider) => (
                  <div key={provider.id}><span className={`health-light ${provider.last_status}`} /><b>{provider.name}</b><code>P{provider.priority} · W{provider.weight}</code><span>{provider.last_latency_ms ? `${provider.last_latency_ms} ms` : "未检查"}</span></div>
                ))}
                {!providers.length && <div className="empty-state"><div><strong>还没有上游</strong>前往“上游路由”添加第一个服务。</div></div>}
              </div>
            </section>
          </div>
        </>
      )}

      {tab === "providers" && (
        <section className="panel">
          <header className="panel-header">
            <div><h2>上游路由</h2><small className="muted">优先级数值越小越先尝试，同级按权重分流。</small></div>
            <div className="toolbar">
              <button className="button button-quiet" disabled={busy} onClick={() => void checkAll()}><RefreshIcon /> 健康检查</button>
              <button className="button button-purple" onClick={() => setProviderModal("new")}><PlusIcon /> 添加上游</button>
            </div>
          </header>
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>名称</th><th>类型 / 地址</th><th>路由</th><th>状态</th><th>延迟</th><th>操作</th></tr></thead>
              <tbody>
                {providers.map((provider) => (
                  <tr key={provider.id}>
                    <td><span className="row-title"><span className={`health-light ${provider.last_status}`} />{provider.name}</span></td>
                    <td><span className="badge">{provider.kind.toUpperCase()}</span><br /><small className="muted mono">{provider.endpoint}</small></td>
                    <td><b>P{provider.priority}</b> / W{provider.weight}</td>
                    <td><span className={`badge ${provider.last_status === "healthy" ? "success" : provider.last_status === "unhealthy" ? "danger" : "warning"}`}>{provider.enabled ? provider.last_status || "unknown" : "disabled"}</span></td>
                    <td>{provider.last_latency_ms ? `${provider.last_latency_ms} ms` : "—"}</td>
                    <td><div className="toolbar nowrap"><button className="mini-action" onClick={() => setProviderModal(provider)}>编辑</button><button className="icon-button danger-icon" onClick={() => void deleteProvider(provider)}><TrashIcon /></button></div></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!providers.length && <div className="empty-state"><div><strong>添加你的第一个翻译上游</strong>支持 DeepL、DeepLX、腾讯、火山、Azure 与百度。</div></div>}
          </div>
        </section>
      )}

      {tab === "playground" && <Playground providers={providers} setMessage={setMessage} />}

      {tab === "logs" && (
        <section className="panel">
          <header className="panel-header"><div><h2>最近请求</h2><small className="muted">保存路由选择、耗时和回退结果。</small></div><button className="button button-quiet" onClick={() => void refresh()}><RefreshIcon /> 刷新</button></header>
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>时间</th><th>请求 ID</th><th>接口</th><th>上游</th><th>耗时</th><th>结果</th></tr></thead>
              <tbody>{logs.map((log) => <tr key={log.id}><td>{formatDate(log.created_at)}</td><td><code>{log.request_id?.slice(0, 10)}</code></td><td><code>{log.route}</code></td><td>{log.provider || "—"}</td><td>{log.latency_ms ?? 0} ms</td><td><span className={`badge ${log.status === "success" ? "success" : "danger"}`}>{log.status}</span></td></tr>)}</tbody>
            </table>
            {!logs.length && <div className="empty-state"><div><strong>暂无请求日志</strong>在“翻译测试”中发送第一条请求。</div></div>}
          </div>
        </section>
      )}

      {tab === "settings" && settings && <SettingsPanel initial={settings} onSaved={(next) => { setSettings(next); setMessage("设置已保存。"); }} />}

      {providerModal && <ProviderModal provider={providerModal === "new" ? null : providerModal} kinds={kinds} onClose={() => setProviderModal(null)} onSaved={async () => { setProviderModal(null); await refresh(); }} />}
    </div>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note: string }) {
  return <div className="stat-card"><span className="label">{label}</span><strong>{value}</strong><small>{note}</small></div>;
}

function ProviderModal({ provider, kinds, onClose, onSaved }: { provider: Provider | null; kinds: ProviderKind[]; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({
    name: provider?.name ?? "",
    kind: provider?.kind ?? kinds[0]?.kind ?? "deepl",
    endpoint: provider?.endpoint ?? kinds[0]?.default_endpoint ?? "https://api-free.deepl.com",
    api_key: "",
    api_secret: "",
    region: "",
    priority: provider?.priority ?? 100,
    weight: provider?.weight ?? 1,
    enabled: provider?.enabled ?? true,
    timeout_seconds: provider?.timeout_seconds ?? 20,
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const update = (key: string, value: string | number | boolean) => setForm((current) => ({ ...current, [key]: value }));

  async function save() {
    setBusy(true);
    try {
      await api(`${API}/providers${provider ? `/${provider.id}` : ""}`, { method: provider ? "PATCH" : "POST", body: JSON.stringify(form) });
      onSaved();
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal wide-modal" onMouseDown={(event) => event.stopPropagation()}>
        <header><h2>{provider ? "编辑上游" : "添加上游"}</h2><button className="icon-button" onClick={onClose}>×</button></header>
        <section>
          {error && <div className="notice error">{error}</div>}
          <div className="form-grid">
            <Field label="名称"><input className="input" value={form.name} onChange={(event) => update("name", event.target.value)} /></Field>
            <Field label="类型"><select className="select" value={form.kind} onChange={(event) => update("kind", event.target.value)}>{kinds.map((kind) => <option value={kind.kind} key={kind.kind}>{kind.label}</option>)}</select></Field>
            <Field label="API 地址" full><input className="input mono" value={form.endpoint} onChange={(event) => update("endpoint", event.target.value)} /></Field>
            <Field label="API Key"><input className="input" type="password" placeholder={provider ? "留空则保持不变" : ""} value={form.api_key} onChange={(event) => update("api_key", event.target.value)} /></Field>
            <Field label="API Secret"><input className="input" type="password" value={form.api_secret} onChange={(event) => update("api_secret", event.target.value)} /></Field>
            <Field label="优先级"><input className="input" type="number" value={form.priority} onChange={(event) => update("priority", Number(event.target.value))} /></Field>
            <Field label="权重"><input className="input" type="number" value={form.weight} onChange={(event) => update("weight", Number(event.target.value))} /></Field>
            <Field label="超时（秒）"><input className="input" type="number" value={form.timeout_seconds} onChange={(event) => update("timeout_seconds", Number(event.target.value))} /></Field>
            <label className="check-field"><input type="checkbox" checked={form.enabled} onChange={(event) => update("enabled", event.target.checked)} /> 启用此上游</label>
          </div>
        </section>
        <footer><button className="button button-quiet" onClick={onClose}>取消</button><button className="button button-purple" disabled={busy || !form.name || !form.endpoint} onClick={() => void save()}>{busy ? "保存中…" : "保存"}</button></footer>
      </div>
    </div>
  );
}

function Playground({ providers, setMessage }: { providers: Provider[]; setMessage: (value: string) => void }) {
  const [text, setText] = useState("Hello! This is a small tool built for real work.");
  const [source, setSource] = useState("auto");
  const [target, setTarget] = useState("ZH");
  const [result, setResult] = useState("");
  const [route, setRoute] = useState("");
  const [busy, setBusy] = useState(false);

  async function translate() {
    setBusy(true);
    setResult("");
    try {
      const data = await api<{ data: string; providers: string[] }>(`${BASE}/translate`, { method: "POST", body: JSON.stringify({ text, source_lang: source, target_lang: target }) });
      setResult(data.data);
      setRoute(data.providers?.join(", ") || "");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="translator">
      <section className="panel">
        <header className="panel-header"><h2>源文本</h2><span className="badge">{text.length} CHARS</span></header>
        <div className="panel-body"><textarea className="textarea translator-text" value={text} onChange={(event) => setText(event.target.value)} /><div className="language-row"><select className="select" value={source} onChange={(event) => setSource(event.target.value)}><option value="auto">自动检测</option><option value="EN">英语</option><option value="ZH">中文</option><option value="JA">日语</option><option value="DE">德语</option></select><span>→</span><select className="select" value={target} onChange={(event) => setTarget(event.target.value)}><option value="ZH">中文</option><option value="EN">英语</option><option value="JA">日语</option><option value="DE">德语</option><option value="FR">法语</option></select></div></div>
      </section>
      <button className="translate-button" disabled={busy || !text || !providers.length} onClick={() => void translate()}>{busy ? "…" : "→"}<small>{providers.length ? "ROUTE" : "NO PROVIDER"}</small></button>
      <section className="panel">
        <header className="panel-header"><h2>翻译结果</h2>{route && <span className="badge success">{route}</span>}</header>
        <div className="panel-body"><div className={`translation-output ${result ? "" : "muted"}`}>{result || "翻译结果会出现在这里。"}</div></div>
      </section>
    </div>
  );
}

function SettingsPanel({ initial, onSaved }: { initial: RouterSettings; onSaved: (next: RouterSettings) => void }) {
  const [form, setForm] = useState(initial);
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true);
    try {
      const next = await api<RouterSettings>(`${API}/settings`, { method: "PUT", body: JSON.stringify(form) });
      onSaved(next);
    } finally {
      setBusy(false);
    }
  }
  return <section className="panel"><header className="panel-header"><div><h2>路由设置</h2><small className="muted">兼容原 DeepL 下游接口。</small></div><SettingsIcon /></header><div className="panel-body settings-form"><Field label="路由模式"><select className="select" value={form.routing_mode} onChange={(event) => setForm({ ...form, routing_mode: event.target.value })}><option value="priority_weighted">优先级 + 加权轮询</option><option value="weighted">全局加权轮询</option></select></Field><label className="check-field"><input type="checkbox" checked={form.fallback_enabled} onChange={(event) => setForm({ ...form, fallback_enabled: event.target.checked })} /> 上游失败时自动回退</label><Field label={`下游访问密钥（${form.downstream_key_hint}）`}><input className="input" type="password" value={form.downstream_key} placeholder="留空保持当前值" onChange={(event) => setForm({ ...form, downstream_key: event.target.value })} /></Field><button className="button button-purple" disabled={busy} onClick={() => void save()}>{busy ? "保存中…" : "保存设置"}</button></div></section>;
}

function Field({ label, full, children }: { label: string; full?: boolean; children: React.ReactNode }) {
  return <div className={`field ${full ? "full" : ""}`}><label>{label}</label>{children}</div>;
}
