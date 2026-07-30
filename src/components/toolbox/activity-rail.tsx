"use client"

import type { LucideIcon } from "lucide-react"
import { BotIcon, CircleHelpIcon, HardDriveIcon, LayoutGridIcon, Settings2Icon } from "lucide-react"
import Link from "next/link"
import { usePathname } from "next/navigation"

import { Button, buttonVariants } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

function RailLink({
  href,
  label,
  icon: Icon,
  active,
}: {
  href: string
  label: string
  icon: LucideIcon
  active: boolean
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Link
            href={href}
            aria-label={label}
            aria-current={active ? "page" : undefined}
            className={cn(
              buttonVariants({ variant: active ? "default" : "ghost", size: "icon-lg" }),
              active && "shadow-[0_8px_24px_var(--accent-shadow)]",
            )}
          />
        }
      >
        <Icon />
      </TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  )
}

export function ActivityRail() {
  const pathname = usePathname()

  return (
    <aside className="fixed inset-y-0 left-0 hidden w-[84px] flex-col items-center border-r border-sidebar-border bg-sidebar py-5 text-sidebar-foreground lg:flex">
      <div className="h-[76px]" aria-hidden="true" />
      <nav className="flex flex-col gap-3" aria-label="工作台快捷导航">
        <RailLink href="/" label="工具首页" icon={LayoutGridIcon} active={pathname === "/"} />
        <RailLink
          href="/tools/ai-model-tester"
          label="模型测试"
          icon={BotIcon}
          active={pathname === "/tools/ai-model-tester"}
        />
        <RailLink
          href="/tools/modal-drive"
          label="Modal 网盘"
          icon={HardDriveIcon}
          active={pathname === "/tools/modal-drive"}
        />
      </nav>
      <div className="mt-5 h-px w-10 bg-sidebar-border" />
      <div className="mt-auto flex flex-col gap-3">
        <Tooltip>
          <TooltipTrigger render={<Button aria-label="设置" variant="ghost" size="icon-lg" />}>
            <Settings2Icon />
          </TooltipTrigger>
          <TooltipContent side="right">设置</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger render={<Button aria-label="帮助" variant="ghost" size="icon-lg" />}>
            <CircleHelpIcon />
          </TooltipTrigger>
          <TooltipContent side="right">帮助</TooltipContent>
        </Tooltip>
      </div>
    </aside>
  )
}
