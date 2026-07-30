import type { Metadata } from "next"

import { AiModelTester } from "@/components/toolbox/ai-model-tester"
import { ToolShell } from "@/components/toolbox/tool-shell"

export const metadata: Metadata = {
  title: "AI 模型测试",
  description: "连接并测试兼容 OpenAI 格式的 AI 模型 API。",
}

export default function AiModelTesterPage() {
  return (
    <ToolShell footerLabel="AI MODEL LAB · OpenAI Compatible">
      <AiModelTester />
    </ToolShell>
  )
}
