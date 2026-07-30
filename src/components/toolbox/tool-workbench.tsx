import { LiveBanner } from "@/components/toolbox/live-banner"
import { ToolDirectory } from "@/components/toolbox/tool-directory"
import { ToolShell } from "@/components/toolbox/tool-shell"

export function ToolWorkbench() {
  return (
    <ToolShell>
      <section className="toolbox-enter" aria-label="实时信息">
        <LiveBanner />
      </section>
      <ToolDirectory />
    </ToolShell>
  )
}
