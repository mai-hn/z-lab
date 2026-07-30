import Link from "next/link"
import {
  ArrowRightIcon,
  BotIcon,
  CloudIcon,
  FolderUpIcon,
  HardDriveIcon,
  Layers3Icon,
  RadioTowerIcon,
  ShieldCheckIcon,
  ZapIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

export function ToolDirectory() {
  return (
    <section className="mt-9" aria-labelledby="tools-title">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="mb-2 font-mono text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
            Tool directory
          </p>
          <h1 id="tools-title" className="text-2xl font-semibold tracking-[-0.035em] sm:text-3xl">
            我的工具
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">选择一个工具进入独立工作区。</p>
        </div>
        <Badge variant="outline">2 TOOLS AVAILABLE</Badge>
      </div>

      <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        <Link
          href="/tools/ai-model-tester"
          className="group rounded-xl outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          aria-label="打开 AI 模型测试工具"
        >
          <Card className="h-full transition-[transform,box-shadow] duration-200 group-hover:-translate-y-1 group-hover:shadow-lg">
            <CardHeader>
              <div className="mb-3 grid size-11 place-items-center rounded-xl bg-primary text-primary-foreground">
                <BotIcon className="size-5" />
              </div>
              <CardTitle className="text-lg">AI 模型测试</CardTitle>
              <CardDescription>连接 OpenAI 兼容接口，测试模型响应与输出差异。</CardDescription>
              <CardAction>
                <Badge variant="secondary">可用</Badge>
              </CardAction>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              <Badge variant="outline"><RadioTowerIcon data-icon="inline-start" />流式输出</Badge>
              <Badge variant="outline"><Layers3Icon data-icon="inline-start" />模型对比</Badge>
              <Badge variant="outline"><ZapIcon data-icon="inline-start" />参数测试</Badge>
            </CardContent>
            <CardFooter className="justify-between text-xs text-muted-foreground transition-colors group-hover:text-foreground">
              <span>OpenAI Compatible</span>
              <span className="flex items-center gap-1.5 font-medium">
                打开工具
                <ArrowRightIcon className="size-3.5 transition-transform group-hover:translate-x-1" />
              </span>
            </CardFooter>
          </Card>
        </Link>

        <Link
          href="/tools/modal-drive"
          className="group rounded-xl outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          aria-label="打开 Modal 网盘工具"
        >
          <Card className="h-full transition-[transform,box-shadow] duration-200 group-hover:-translate-y-1 group-hover:shadow-lg">
            <CardHeader>
              <div className="mb-3 grid size-11 place-items-center rounded-xl bg-primary text-primary-foreground">
                <HardDriveIcon className="size-5" />
              </div>
              <CardTitle className="text-lg">Modal 网盘</CardTitle>
              <CardDescription>将 Modal Volume 作为个人云盘，管理目录、上传和下载文件。</CardDescription>
              <CardAction>
                <Badge variant="secondary">NEW</Badge>
              </CardAction>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              <Badge variant="outline"><FolderUpIcon data-icon="inline-start" />文件管理</Badge>
              <Badge variant="outline"><CloudIcon data-icon="inline-start" />Volume</Badge>
              <Badge variant="outline"><ShieldCheckIcon data-icon="inline-start" />服务端鉴权</Badge>
            </CardContent>
            <CardFooter className="justify-between text-xs text-muted-foreground transition-colors group-hover:text-foreground">
              <span>Python · FastAPI</span>
              <span className="flex items-center gap-1.5 font-medium">
                打开工具
                <ArrowRightIcon className="size-3.5 transition-transform group-hover:translate-x-1" />
              </span>
            </CardFooter>
          </Card>
        </Link>
      </div>
    </section>
  )
}
