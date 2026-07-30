"use client"

import { BoxIcon, MoonIcon, SunIcon } from "lucide-react"
import Link from "next/link"
import { useTheme } from "next-themes"
import { usePathname } from "next/navigation"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

const navigation = [
  { href: "/", label: "工具首页" },
  { href: "/tools/ai-model-tester", label: "模型测试" },
  { href: "/tools/modal-drive", label: "Modal 网盘" },
]

export function AppHeader() {
  const { resolvedTheme, setTheme } = useTheme()
  const pathname = usePathname()
  const dark = resolvedTheme === "dark"

  return (
    <header className="sticky top-0 z-20 flex h-[86px] items-center border-b bg-background/95 px-5 backdrop-blur md:px-8 lg:ml-[84px] lg:px-12">
      <div className="flex min-w-0 flex-1 items-center">
        <Link className="flex items-center gap-3" href="/" aria-label="TOOLBOX 首页">
          <span className="grid size-9 place-items-center rounded-md bg-primary text-primary-foreground">
            <BoxIcon className="size-5" strokeWidth={2.2} />
          </span>
          <span className="text-lg font-bold tracking-[-0.03em] sm:text-xl">TOOLBOX</span>
        </Link>
      </div>
      <nav className="hidden h-full items-stretch md:flex" aria-label="主导航">
        {navigation.map((item) => {
          const active = pathname === item.href

          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "relative flex items-center px-6 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground",
                active && "text-foreground after:absolute after:inset-x-5 after:bottom-0 after:h-0.5 after:bg-primary",
              )}
            >
              {item.label}
            </Link>
          )
        })}
      </nav>
      <div className="flex flex-1 items-center justify-end gap-2 sm:gap-3">
        <Badge variant="outline" className="hidden sm:inline-flex">
          <BoxIcon data-icon="inline-start" />
          TOOLBOX LAB
        </Badge>
        <Button
          aria-label={dark ? "切换到浅色模式" : "切换到深色模式"}
          variant="outline"
          size="icon-lg"
          onClick={() => setTheme(dark ? "light" : "dark")}
        >
          {dark ? <SunIcon /> : <MoonIcon />}
        </Button>
      </div>
    </header>
  )
}
