export type ProjectAccent = "yellow" | "purple" | "green";

export type LabProject = {
  id: string;
  number: string;
  name: string;
  shortName: string;
  description: string;
  longDescription: string;
  href: string;
  accent: ProjectAccent;
  tag: string;
  stack: string[];
  capabilities: string[];
  external?: string;
};

export const projects: LabProject[] = [
  {
    id: "modal-drive",
    number: "01",
    name: "Modal Drive",
    shortName: "DRIVE",
    description: "轻量、可恢复的分片云端文件管理。",
    longDescription:
      "大文件直接分片进入 Modal Volume，本地只保留可查询的元数据；复制和移动不会重复占用远端空间。",
    href: "/projects/drive",
    accent: "yellow",
    tag: "STORAGE",
    stack: ["NEXT.JS", "FASTAPI", "MODAL"],
    capabilities: ["8 MiB 自动分片", "顺序流式下载", "元数据级复制与移动"],
  },
  {
    id: "deepl-router",
    number: "02",
    name: "DeepRouter",
    shortName: "ROUTER",
    description: "把多个翻译上游变成一个稳定端点。",
    longDescription:
      "根据优先级、权重和实时健康状态选择上游，失败时自动回退，同时保留 DeepL 兼容接口。",
    href: "/projects/router",
    accent: "purple",
    tag: "ROUTING",
    stack: ["NEXT.JS", "FASTAPI", "SQLITE"],
    capabilities: ["健康检查", "优先级回退", "DeepL 兼容 API"],
    external: "https://github.com/mai-hn/deepl-router",
  },
  {
    id: "ai-model-checker",
    number: "03",
    name: "AI Model Checker",
    shortName: "MODELS",
    description: "发现并测试 OpenAI 兼容模型。",
    longDescription:
      "读取服务端模型列表，通过单次生成或多轮对话验证模型能力；凭据仅保存在当前浏览器。",
    href: "/projects/models",
    accent: "green",
    tag: "AI TOOLS",
    stack: ["NEXT.JS", "FASTAPI", "OPENAI API"],
    capabilities: ["模型发现", "流式生成", "多轮对话"],
    external: "https://github.com/mai-hn/ai-model-checker",
  },
];

export function getProject(id: string) {
  return projects.find((project) => project.id === id);
}
