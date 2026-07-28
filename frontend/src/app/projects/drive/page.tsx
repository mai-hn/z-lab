"use client";

import { ChangeEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  DownloadIcon,
  DriveIcon,
  FileIcon,
  FolderIcon,
  PlusIcon,
  RefreshIcon,
  TrashIcon,
  UploadIcon,
} from "@/components/icons";
import { api, formatBytes, formatDate } from "@/lib/api";

type FileNode = {
  id: string;
  parent_id: string | null;
  name: string;
  node_type: "file" | "directory";
  size: number;
  chunk_count: number;
  storage_layout: string;
  path: string;
  modified_at: string;
};

type Listing = { path: string; node: FileNode | null; items: FileNode[]; total: number };
type Stats = {
  used_bytes: number;
  logical_bytes: number;
  saved_bytes: number;
  chunked_files: number;
  file_count: number;
  directory_count: number;
  offline_tasks: number;
};
type OfflineTask = {
  id: string;
  url: string;
  filename?: string;
  status: string;
  progress: number;
  downloaded_size: number;
  total_size: number;
  speed: number;
  error_message?: string;
  created_at: string;
};

const BASE = "/api/drive";
const EIGHT_MIB = 8 * 1024 * 1024;
const CHUNK_SIZE = 4 * 1024 * 1024;

export default function DrivePage() {
  const [tab, setTab] = useState<"files" | "offline" | "storage">("files");
  const [listing, setListing] = useState<Listing>({ path: "/", node: null, items: [], total: 0 });
  const [stats, setStats] = useState<Stats | null>(null);
  const [tasks, setTasks] = useState<OfflineTask[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [modal, setModal] = useState<null | { type: string; node?: FileNode }>(null);
  const [value, setValue] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async (path = listing.path) => {
    try {
      const [nextListing, nextStats] = await Promise.all([
        api<Listing>(`${BASE}/files?path=${encodeURIComponent(path)}`),
        api<Stats>(`${BASE}/stats`),
      ]);
      setListing(nextListing);
      setStats(nextStats);
      setMessage("");
    } catch (error) {
      setMessage((error as Error).message);
    }
  }, [listing.path]);

  const refreshTasks = useCallback(async () => {
    try {
      setTasks(await api<OfflineTask[]>(`${BASE}/offline`));
    } catch (error) {
      setMessage((error as Error).message);
    }
  }, []);

  useEffect(() => {
    void refresh("/");
    void refreshTasks();
    // Initial fetch only; subsequent navigation calls refresh explicitly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!tasks.some((task) => ["pending", "running"].includes(task.status))) return;
    const timer = window.setInterval(() => void refreshTasks(), 1800);
    return () => window.clearInterval(timer);
  }, [tasks, refreshTasks]);

  async function upload(file: File) {
    setBusy(true);
    setMessage("");
    try {
      if (file.size <= EIGHT_MIB) {
        const body = new FormData();
        body.append("file", file);
        body.append("path", listing.path);
        await api(`${BASE}/upload`, { method: "POST", body });
        setUploadProgress(100);
      } else {
        const session = await api<{ id: string; total_chunks: number }>(`${BASE}/uploads`, {
          method: "POST",
          body: JSON.stringify({
            filename: file.name,
            total_size: file.size,
            path: listing.path,
            chunk_size: CHUNK_SIZE,
            conflict: "rename",
          }),
        });
        for (let index = 0; index < session.total_chunks; index += 1) {
          const start = index * CHUNK_SIZE;
          const body = new FormData();
          body.append("file", file.slice(start, Math.min(start + CHUNK_SIZE, file.size)), file.name);
          await api(`${BASE}/uploads/${session.id}/parts/${index}`, { method: "PUT", body });
          setUploadProgress(Math.round(((index + 1) / session.total_chunks) * 100));
        }
        await api(`${BASE}/uploads/${session.id}/complete`, {
          method: "POST",
          body: JSON.stringify({}),
        });
      }
      await refresh();
      window.setTimeout(() => setUploadProgress(null), 1200);
    } catch (error) {
      setMessage((error as Error).message);
      setUploadProgress(null);
    } finally {
      setBusy(false);
    }
  }

  async function handleFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    for (const file of files) await upload(file);
    event.target.value = "";
  }

  function openModal(type: string, node?: FileNode) {
    setValue(type === "rename" ? node?.name ?? "" : "");
    setModal({ type, node });
  }

  async function submitModal() {
    if (!modal) return;
    setBusy(true);
    try {
      if (modal.type === "folder") {
        await api(`${BASE}/files/directories`, {
          method: "POST",
          body: JSON.stringify({ name: value, path: listing.path }),
        });
      } else if (modal.type === "rename" && modal.node) {
        await api(`${BASE}/files/${modal.node.id}/rename`, {
          method: "POST",
          body: JSON.stringify({ name: value }),
        });
      } else if (modal.type === "copy" && modal.node) {
        await api(`${BASE}/files/${modal.node.id}/copy`, {
          method: "POST",
          body: JSON.stringify({ target_path: value || listing.path }),
        });
      } else if (modal.type === "move" && modal.node) {
        await api(`${BASE}/files/${modal.node.id}/move`, {
          method: "POST",
          body: JSON.stringify({ target_path: value || "/" }),
        });
      } else if (modal.type === "delete" && modal.node) {
        await api(`${BASE}/files/${modal.node.id}`, { method: "DELETE" });
      } else if (modal.type === "offline") {
        await api(`${BASE}/offline`, {
          method: "POST",
          body: JSON.stringify({ url: value, path: listing.path }),
        });
        await refreshTasks();
      }
      setModal(null);
      setValue("");
      await refresh();
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function parentPath() {
    const parts = listing.path.split("/").filter(Boolean);
    parts.pop();
    return `/${parts.join("/")}` || "/";
  }

  return (
    <div className="workspace-page accent-yellow">
      <div className="workspace-header">
        <div className="workspace-title">
          <span className="workspace-icon">
            <DriveIcon size={34} />
          </span>
          <div>
            <span className="eyebrow">PROJECT 01 / STORAGE</span>
            <h1>Modal Drive</h1>
          </div>
        </div>
        <div className="workspace-status">
          <span className="status-dot" /> METADATA-FIRST · READY
        </div>
      </div>

      <nav className="tabs">
        {[
          ["files", "文件"],
          ["offline", "离线下载"],
          ["storage", "存储模型"],
        ].map(([id, label]) => (
          <button className={`tab ${tab === id ? "active" : ""}`} onClick={() => setTab(id as typeof tab)} key={id}>
            {label}
          </button>
        ))}
      </nav>

      {message && <p className="notice error">{message}</p>}

      {tab === "files" && (
        <>
          <div className="stats-grid">
            <Stat label="LOGICAL SIZE" value={formatBytes(stats?.logical_bytes)} note="用户可见文件总量" />
            <Stat label="REMOTE USED" value={formatBytes(stats?.used_bytes)} note="去重后实际占用" />
            <Stat label="SAVED" value={formatBytes(stats?.saved_bytes)} note="元数据复制节省" />
            <Stat label="CHUNKED" value={String(stats?.chunked_files ?? 0)} note="大于 8 MiB 的文件" />
          </div>
          <section className="panel">
            <header className="panel-header">
              <div>
                <h2 className="mono">{listing.path}</h2>
                <small className="muted">{listing.total} 个项目</small>
              </div>
              <div className="toolbar">
                <button className="button button-quiet" onClick={() => openModal("folder")}>
                  <PlusIcon /> 新建文件夹
                </button>
                <button className="button button-dark" onClick={() => fileInput.current?.click()} disabled={busy}>
                  <UploadIcon /> 上传文件
                </button>
                <input ref={fileInput} type="file" hidden multiple onChange={handleFiles} />
              </div>
            </header>
            {uploadProgress !== null && (
              <div className="upload-strip">
                <span style={{ width: `${uploadProgress}%` }} />
                <b>{uploadProgress}% · {busy ? "正在顺序上传分片" : "上传完成"}</b>
              </div>
            )}
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>名称</th>
                    <th>大小</th>
                    <th>存储</th>
                    <th>修改时间</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {listing.path !== "/" && (
                    <tr className="clickable-row" onClick={() => void refresh(parentPath())}>
                      <td>
                        <span className="row-title"><FolderIcon /> ..</span>
                      </td>
                      <td colSpan={4} className="muted">返回上一级</td>
                    </tr>
                  )}
                  {listing.items.map((node) => (
                    <tr key={node.id}>
                      <td>
                        <button
                          className="row-name"
                          onClick={() =>
                            node.node_type === "directory"
                              ? void refresh(node.path)
                              : window.open(`${BASE}/files/${node.id}/content`, "_blank")
                          }
                        >
                          {node.node_type === "directory" ? <FolderIcon /> : <FileIcon />}
                          <span>{node.name}</span>
                        </button>
                      </td>
                      <td>{node.node_type === "file" ? formatBytes(node.size) : "—"}</td>
                      <td>
                        {node.node_type === "file" && (
                          <span className={`badge ${node.chunk_count > 1 ? "success" : ""}`}>
                            {node.chunk_count > 1 ? `${node.chunk_count} CHUNKS` : "SINGLE"}
                          </span>
                        )}
                      </td>
                      <td>{formatDate(node.modified_at)}</td>
                      <td>
                        <div className="toolbar nowrap">
                          {node.node_type === "file" && (
                            <a className="icon-button" href={`${BASE}/files/${node.id}/content`} title="下载">
                              <DownloadIcon />
                            </a>
                          )}
                          <button className="mini-action" onClick={() => openModal("rename", node)}>改名</button>
                          <button className="mini-action" onClick={() => openModal("copy", node)}>复制</button>
                          <button className="mini-action" onClick={() => openModal("move", node)}>移动</button>
                          <button className="icon-button danger-icon" onClick={() => openModal("delete", node)} title="删除">
                            <TrashIcon />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!listing.items.length && listing.path === "/" && (
                <div className="empty-state">
                  <div><strong>这里还没有文件</strong>拖入文件，或使用右上角上传按钮开始。</div>
                </div>
              )}
            </div>
          </section>
        </>
      )}

      {tab === "offline" && (
        <section className="panel">
          <header className="panel-header">
            <div>
              <h2>离线下载任务</h2>
              <small className="muted">Modal 端下载并按 4 MiB 分片写入；本地只记录任务和文件清单。</small>
            </div>
            <div className="toolbar">
              <button className="button button-quiet" onClick={() => void refreshTasks()}><RefreshIcon /> 刷新</button>
              <button className="button button-dark" onClick={() => openModal("offline")}><PlusIcon /> 新建任务</button>
            </div>
          </header>
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>文件 / URL</th><th>进度</th><th>已下载</th><th>速度</th><th>状态</th></tr></thead>
              <tbody>
                {tasks.map((task) => (
                  <tr key={task.id}>
                    <td>
                      <span className="row-title">{task.filename || task.url}</span>
                      <small className="muted mono">{task.url.slice(0, 72)}</small>
                    </td>
                    <td>
                      <div className="inline-progress"><span style={{ width: `${task.progress}%` }} /></div>
                      <small>{Math.round(task.progress)}%</small>
                    </td>
                    <td>{formatBytes(task.downloaded_size)} / {task.total_size ? formatBytes(task.total_size) : "?"}</td>
                    <td>{formatBytes(task.speed)}/s</td>
                    <td><span className={`badge ${task.status === "completed" ? "success" : task.status === "failed" ? "danger" : "warning"}`}>{task.status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!tasks.length && <div className="empty-state"><div><strong>没有离线任务</strong>粘贴 HTTP / HTTPS 链接即可开始。</div></div>}
          </div>
        </section>
      )}

      {tab === "storage" && (
        <div className="storage-flow">
          <FlowCard index="01" title="BROWSER" text="读取文件字节数；超过 8 MiB 时按 4 MiB 切片。" />
          <span className="flow-arrow">→</span>
          <FlowCard index="02" title="PYTHON API" text="保存文件元数据、分片清单、引用关系与任务状态。" />
          <span className="flow-arrow">→</span>
          <FlowCard index="03" title="MODAL VOLUME" text="只保存真实内容块；复制和移动不产生新内容。" />
          <div className="panel storage-note">
            <h2>成本优先的边界</h2>
            <p>本地没有持久文件缓存。删除最后一个数据库引用时才调用 Modal API 删除远端分片；浏览器下载通过带有 Content-Length、X-File-Size 与 Range 的顺序流返回，因此可以显示原生下载进度并支持续传。</p>
          </div>
        </div>
      )}

      {modal && (
        <div className="modal-backdrop" onMouseDown={() => setModal(null)}>
          <div className="modal" onMouseDown={(event) => event.stopPropagation()}>
            <header>
              <h2>{modalTitle(modal.type)}</h2>
              <button className="icon-button" onClick={() => setModal(null)}>×</button>
            </header>
            <section>
              {modal.type === "delete" ? (
                <p>将删除“{modal.node?.name}”。如果这是内容的最后一个引用，后端会通过 Modal API 删除所有远端分片。此操作无法撤销。</p>
              ) : (
                <div className="field">
                  <label>{modal.type === "offline" ? "下载地址" : modal.type === "folder" || modal.type === "rename" ? "名称" : "目标目录路径"}</label>
                  <input
                    className="input"
                    value={value}
                    placeholder={modal.type === "offline" ? "https://example.com/file.zip" : modal.type === "copy" || modal.type === "move" ? "/" : ""}
                    autoFocus
                    onChange={(event) => setValue(event.target.value)}
                    onKeyDown={(event) => event.key === "Enter" && void submitModal()}
                  />
                </div>
              )}
            </section>
            <footer>
              <button className="button button-quiet" onClick={() => setModal(null)}>取消</button>
              <button className={`button ${modal.type === "delete" ? "button-danger" : "button-dark"}`} disabled={busy || (!value && !["delete", "copy", "move"].includes(modal.type))} onClick={() => void submitModal()}>
                {busy ? "处理中…" : "确认"}
              </button>
            </footer>
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note: string }) {
  return <div className="stat-card"><span className="label">{label}</span><strong>{value}</strong><small>{note}</small></div>;
}

function FlowCard({ index, title, text }: { index: string; title: string; text: string }) {
  return <div className="flow-card"><b>{index}</b><DriveIcon size={34} /><h2>{title}</h2><p>{text}</p></div>;
}

function modalTitle(type: string) {
  return { folder: "新建文件夹", rename: "重命名", copy: "复制（只创建元数据引用）", move: "移动", delete: "确认删除", offline: "新建离线下载" }[type] ?? "操作";
}
