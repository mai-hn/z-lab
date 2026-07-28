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
type Transfer = {
  id: string;
  name: string;
  direction: "upload" | "download";
  status: "running" | "completed" | "failed" | "cancelled";
  transferred: number;
  total: number;
  speed: number;
  error?: string;
};
type SpeedSample = { bytes: number; at: number; speed: number };
type UploadSession = { id: string; total_chunks: number; chunk_size: number };
type WritableTarget = {
  write(data: Uint8Array): Promise<void>;
  close(): Promise<void>;
  abort?(): Promise<void>;
};
type SavePickerWindow = Window & {
  showSaveFilePicker?: (options: { suggestedName: string }) => Promise<{
    createWritable(): Promise<WritableTarget>;
  }>;
};

const BASE = "/api/drive";
const EIGHT_MIB = 8 * 1024 * 1024;
const CHUNK_SIZE = 4 * 1024 * 1024;
const ACTIVE_OFFLINE_STATUSES = new Set(["pending", "downloading"]);
const ACTIVE_TRANSFER_STATUS = "running";

function transferId() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
}

function xhrUpload(url: string, body: FormData, onProgress: (loaded: number) => void) {
  return new Promise<void>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("PUT", url);
    request.upload.onprogress = (event) => onProgress(event.loaded);
    request.onerror = () => reject(new Error("上传连接中断"));
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        resolve();
        return;
      }
      try {
        const payload = JSON.parse(request.responseText);
        reject(new Error(payload.detail?.message ?? payload.detail ?? request.statusText));
      } catch {
        reject(new Error(request.statusText || `上传失败 (${request.status})`));
      }
    };
    request.send(body);
  });
}

export default function DrivePage() {
  const [tab, setTab] = useState<"files" | "offline" | "storage">("files");
  const [listing, setListing] = useState<Listing>({ path: "/", node: null, items: [], total: 0 });
  const [stats, setStats] = useState<Stats | null>(null);
  const [tasks, setTasks] = useState<OfflineTask[]>([]);
  const [transfers, setTransfers] = useState<Transfer[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [modal, setModal] = useState<null | { type: string; node?: FileNode }>(null);
  const [value, setValue] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const listingPath = useRef("/");
  const transferSamples = useRef(new Map<string, SpeedSample>());
  const offlineSamples = useRef(new Map<string, SpeedSample>());

  const refresh = useCallback(async (path?: string) => {
    const targetPath = path ?? listingPath.current;
    try {
      const [nextListing, nextStats] = await Promise.all([
        api<Listing>(`${BASE}/files?path=${encodeURIComponent(targetPath)}`),
        api<Stats>(`${BASE}/stats`),
      ]);
      listingPath.current = nextListing.path;
      setListing(nextListing);
      setStats(nextStats);
      setMessage("");
    } catch (error) {
      setMessage((error as Error).message);
    }
  }, []);

  const refreshTasks = useCallback(async () => {
    try {
      const now = performance.now();
      const nextTasks = await api<OfflineTask[]>(`${BASE}/offline`);
      const activeIds = new Set<string>();
      const measured = nextTasks.map((task) => {
        if (!ACTIVE_OFFLINE_STATUSES.has(task.status)) {
          offlineSamples.current.delete(task.id);
          return { ...task, speed: 0 };
        }
        activeIds.add(task.id);
        const previous = offlineSamples.current.get(task.id);
        const elapsed = previous ? (now - previous.at) / 1000 : 0;
        const delta = previous ? Math.max(0, task.downloaded_size - previous.bytes) : 0;
        const instant = elapsed > 0 ? delta / elapsed : 0;
        const speed = previous ? previous.speed * 0.35 + instant * 0.65 : 0;
        offlineSamples.current.set(task.id, {
          bytes: task.downloaded_size,
          at: now,
          speed,
        });
        return { ...task, speed };
      });
      for (const id of offlineSamples.current.keys()) {
        if (!activeIds.has(id)) offlineSamples.current.delete(id);
      }
      setTasks(measured);
    } catch (error) {
      setMessage((error as Error).message);
    }
  }, []);

  useEffect(() => {
    void refresh("/");
    void refreshTasks();
  }, [refresh, refreshTasks]);

  const hasActiveOffline = tasks.some((task) => ACTIVE_OFFLINE_STATUSES.has(task.status));
  useEffect(() => {
    if (!hasActiveOffline) return;
    const timer = window.setInterval(() => {
      void refreshTasks();
      void refresh();
    }, 1500);
    return () => window.clearInterval(timer);
  }, [hasActiveOffline, refresh, refreshTasks]);

  const hasActiveTransfer = transfers.some((transfer) => transfer.status === ACTIVE_TRANSFER_STATUS);
  useEffect(() => {
    if (!hasActiveTransfer) return;
    const timer = window.setInterval(() => void refresh(), 1800);
    return () => window.clearInterval(timer);
  }, [hasActiveTransfer, refresh]);

  function addTransfer(name: string, direction: Transfer["direction"], total: number) {
    const id = transferId();
    transferSamples.current.set(id, { bytes: 0, at: performance.now(), speed: 0 });
    setTransfers((current) => [
      {
        id,
        name,
        direction,
        status: "running",
        transferred: 0,
        total,
        speed: 0,
      },
      ...current,
    ]);
    return id;
  }

  function updateTransfer(id: string, bytes: number, total?: number) {
    const now = performance.now();
    const previous = transferSamples.current.get(id);
    const elapsed = previous ? (now - previous.at) / 1000 : 0;
    const delta = previous ? Math.max(0, bytes - previous.bytes) : 0;
    const instant = elapsed > 0 ? delta / elapsed : 0;
    const speed = previous ? previous.speed * 0.35 + instant * 0.65 : 0;
    transferSamples.current.set(id, { bytes, at: now, speed });
    setTransfers((current) =>
      current.map((transfer) =>
        transfer.id === id
          ? { ...transfer, transferred: bytes, total: total ?? transfer.total, speed }
          : transfer,
      ),
    );
  }

  function finishTransfer(
    id: string,
    status: Transfer["status"],
    error?: string,
  ) {
    transferSamples.current.delete(id);
    setTransfers((current) =>
      current.map((transfer) =>
        transfer.id === id
          ? {
              ...transfer,
              status,
              transferred: status === "completed" ? transfer.total : transfer.transferred,
              speed: 0,
              error,
            }
          : transfer,
      ),
    );
  }

  async function upload(file: File) {
    const id = addTransfer(file.name, "upload", file.size);
    setBusy(true);
    setMessage("");
    try {
      const session = await api<UploadSession>(`${BASE}/uploads`, {
        method: "POST",
        body: JSON.stringify({
          filename: file.name,
          total_size: file.size,
          path: listingPath.current,
          // Keep small files to one remote write; only files over 8 MiB need
          // multiple 4 MiB parts.
          chunk_size: file.size > EIGHT_MIB ? CHUNK_SIZE : EIGHT_MIB,
          conflict: "rename",
        }),
      });
      for (let index = 0; index < session.total_chunks; index += 1) {
        const start = index * session.chunk_size;
        const end = Math.min(start + session.chunk_size, file.size);
        const body = new FormData();
        body.append("file", file.slice(start, end), file.name);
        await xhrUpload(
          `${BASE}/uploads/${session.id}/parts/${index}`,
          body,
          (loaded) => updateTransfer(id, Math.min(start + loaded, end)),
        );
        updateTransfer(id, end);
      }
      await api(`${BASE}/uploads/${session.id}/complete`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      finishTransfer(id, "completed");
      await refresh();
    } catch (error) {
      const detail = (error as Error).message;
      finishTransfer(id, "failed", detail);
      setMessage(detail);
    } finally {
      setBusy(false);
    }
  }

  async function download(node: FileNode) {
    const id = addTransfer(node.name, "download", node.size);
    let writable: WritableTarget | null = null;
    try {
      const picker = (window as SavePickerWindow).showSaveFilePicker;
      if (picker) {
        const handle = await picker({ suggestedName: node.name });
        writable = await handle.createWritable();
      }
      const response = await fetch(`${BASE}/files/${node.id}/content`);
      if (!response.ok || !response.body) {
        const payload = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(payload.detail?.message ?? payload.detail ?? "下载失败");
      }
      const total = Number(response.headers.get("x-file-size") || response.headers.get("content-length")) || node.size;
      const reader = response.body.getReader();
      const memoryChunks: BlobPart[] = [];
      let received = 0;
      while (true) {
        const { done, value: chunk } = await reader.read();
        if (done) break;
        received += chunk.byteLength;
        if (writable) {
          await writable.write(chunk);
        } else {
          memoryChunks.push(new Uint8Array(chunk));
        }
        updateTransfer(id, received, total);
      }
      if (writable) {
        await writable.close();
      } else {
        const url = URL.createObjectURL(new Blob(memoryChunks));
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = node.name;
        anchor.click();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
      finishTransfer(id, "completed");
    } catch (error) {
      const cancelled = (error as DOMException).name === "AbortError";
      if (writable?.abort) await writable.abort().catch(() => undefined);
      const detail = cancelled ? "用户取消了下载" : (error as Error).message;
      finishTransfer(id, cancelled ? "cancelled" : "failed", detail);
      if (!cancelled) setMessage(detail);
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
          <span className="workspace-icon"><DriveIcon size={34} /></span>
          <div>
            <span className="eyebrow">PROJECT 01 / STORAGE</span>
            <h1>Modal Drive</h1>
          </div>
        </div>
        <div className="workspace-status"><span className="status-dot" /> METADATA-FIRST · READY</div>
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

      {message ? <p className="notice error">{message}</p> : null}

      {tab === "files" ? (
        <>
          <div className="stats-grid">
            <Stat label="LOGICAL SIZE" value={formatBytes(stats?.logical_bytes)} note="用户可见文件总量" />
            <Stat label="REMOTE USED" value={formatBytes(stats?.used_bytes)} note="去重后实际占用" />
            <Stat label="SAVED" value={formatBytes(stats?.saved_bytes)} note="元数据复制节省" />
            <Stat label="CHUNKED" value={String(stats?.chunked_files ?? 0)} note="大于 8 MiB 的文件" />
          </div>

          {transfers.length ? (
            <section className="panel transfer-panel">
              <header className="panel-header">
                <div>
                  <h2>本机传输</h2>
                  <small className="muted">进度和速度由当前浏览器按实际收发字节计算。</small>
                </div>
                <button
                  className="button button-quiet"
                  onClick={() => setTransfers((current) => current.filter((item) => item.status === "running"))}
                  disabled={transfers.every((item) => item.status === "running")}
                >
                  清除已结束
                </button>
              </header>
              <div className="transfer-list">
                {transfers.map((transfer) => (
                  <TransferRow transfer={transfer} key={transfer.id} />
                ))}
              </div>
            </section>
          ) : null}

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
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr><th>名称</th><th>大小</th><th>存储</th><th>修改时间</th><th>操作</th></tr>
                </thead>
                <tbody>
                  {listing.path !== "/" ? (
                    <tr className="clickable-row" onClick={() => void refresh(parentPath())}>
                      <td><span className="row-title"><FolderIcon /> ..</span></td>
                      <td colSpan={4} className="muted">返回上一级</td>
                    </tr>
                  ) : null}
                  {listing.items.map((node) => (
                    <tr key={node.id}>
                      <td>
                        <button
                          className="row-name"
                          onClick={() => node.node_type === "directory" ? void refresh(node.path) : void download(node)}
                        >
                          {node.node_type === "directory" ? <FolderIcon /> : <FileIcon />}
                          <span>{node.name}</span>
                        </button>
                      </td>
                      <td>{node.node_type === "file" ? formatBytes(node.size) : "—"}</td>
                      <td>
                        {node.node_type === "file" ? (
                          <span className={`badge ${node.chunk_count > 1 ? "success" : ""}`}>
                            {node.chunk_count > 1 ? `${node.chunk_count} CHUNKS` : "SINGLE"}
                          </span>
                        ) : null}
                      </td>
                      <td>{formatDate(node.modified_at)}</td>
                      <td>
                        <div className="toolbar nowrap">
                          {node.node_type === "file" ? (
                            <button className="icon-button" onClick={() => void download(node)} title="下载">
                              <DownloadIcon />
                            </button>
                          ) : null}
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
              {!listing.items.length && listing.path === "/" ? (
                <div className="empty-state"><div><strong>这里还没有文件</strong>使用右上角上传按钮开始。</div></div>
              ) : null}
            </div>
          </section>
        </>
      ) : null}

      {tab === "offline" ? (
        <section className="panel">
          <header className="panel-header">
            <div>
              <h2>离线下载任务</h2>
              <small className="muted">每 1.5 秒自动刷新；速度由本机根据任务字节增量计算。</small>
            </div>
            <div className="toolbar">
              <button className="button button-quiet" onClick={() => void refreshTasks()}><RefreshIcon /> 刷新</button>
              <button className="button button-dark" onClick={() => openModal("offline")}><PlusIcon /> 新建任务</button>
            </div>
          </header>
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>文件 / URL</th><th>进度</th><th>已下载</th><th>本机速度</th><th>状态</th></tr></thead>
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
                    <td>{ACTIVE_OFFLINE_STATUSES.has(task.status) ? `${formatBytes(task.speed)}/s` : "—"}</td>
                    <td>
                      <span className={`badge ${task.status === "completed" ? "success" : task.status === "failed" ? "danger" : "warning"}`}>
                        {task.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!tasks.length ? <div className="empty-state"><div><strong>没有离线任务</strong>粘贴 HTTP / HTTPS 链接即可开始。</div></div> : null}
          </div>
        </section>
      ) : null}

      {tab === "storage" ? (
        <div className="storage-flow">
          <FlowCard index="01" title="BROWSER" text="上传与下载实时读取本机传输字节，自动计算进度和速度。" />
          <span className="flow-arrow">→</span>
          <FlowCard index="02" title="PYTHON API" text="保存文件元数据、分片清单、DAV 属性与引用关系。" />
          <span className="flow-arrow">→</span>
          <FlowCard index="03" title="MODAL VOLUME" text="超过 8 MiB 按块存储；复制和移动不复制真实内容。" />
          <div className="panel storage-note">
            <h2>WebDAV 已启用</h2>
            <p>
              服务地址为 <code>http(s)://host:port/dav</code>。支持 OPTIONS、PROPFIND、GET、HEAD、
              PUT、MKCOL、DELETE、MOVE、COPY 与 PROPPATCH；设置 DRIVE_API_TOKEN 后，以任意用户名和
              token 作为密码登录。
            </p>
          </div>
          <div className="panel storage-note storage-note-secondary">
            <h2>成本优先的边界</h2>
            <p>本地没有持久文件缓存。删除最后一个数据库引用时才调用 Modal API 回收远端分片；支持流式下载和 Range 续传。</p>
          </div>
        </div>
      ) : null}

      {modal ? (
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
              <button
                className={`button ${modal.type === "delete" ? "button-danger" : "button-dark"}`}
                disabled={busy || (!value && !["delete", "copy", "move"].includes(modal.type))}
                onClick={() => void submitModal()}
              >
                {busy ? "处理中…" : "确认"}
              </button>
            </footer>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function TransferRow({ transfer }: { transfer: Transfer }) {
  const progress = transfer.total > 0
    ? Math.min(100, Math.round((transfer.transferred / transfer.total) * 100))
    : 0;
  const label = {
    running: "传输中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
  }[transfer.status];
  return (
    <div className="transfer-row">
      <span className={`transfer-direction ${transfer.direction}`}>
        {transfer.direction === "upload" ? <UploadIcon /> : <DownloadIcon />}
      </span>
      <div className="transfer-main">
        <div className="transfer-meta">
          <strong>{transfer.name}</strong>
          <span>{formatBytes(transfer.transferred)} / {formatBytes(transfer.total)}</span>
        </div>
        <div className="transfer-track"><span style={{ width: `${progress}%` }} /></div>
        {transfer.error ? <small className="transfer-error">{transfer.error}</small> : null}
      </div>
      <div className="transfer-rate">
        <strong>{progress}%</strong>
        <span>{transfer.status === "running" ? `${formatBytes(transfer.speed)}/s` : label}</span>
      </div>
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
