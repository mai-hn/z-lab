import type { ReactNode } from "react"

import { ActivityRail } from "@/components/toolbox/activity-rail"
import { AppHeader } from "@/components/toolbox/app-header"
import { Separator } from "@/components/ui/separator"

export function ToolShell({
  children,
  footerLabel = "PERSONAL TOOLBOX",
}: {
  children: ReactNode
  footerLabel?: string
}) {
  return (
    <div id="top" className="min-h-screen bg-background text-foreground">
      <ActivityRail />
      <AppHeader />

      <main className="toolbox-grid min-h-[calc(100vh-86px)] lg:ml-[84px]">
        <div className="mx-auto flex w-full max-w-[1260px] flex-col px-5 pb-8 pt-8 sm:px-8 md:pt-10 lg:px-12">
          {children}

          <footer className="mt-8 flex items-center gap-4 text-xs text-muted-foreground">
            <Separator className="flex-1" />
            <span>{footerLabel}</span>
            <Separator className="flex-1" />
          </footer>
        </div>
      </main>
    </div>
  )
}
