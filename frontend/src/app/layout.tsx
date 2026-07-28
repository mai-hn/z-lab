import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Z-Lab — 小而可靠的工具",
    template: "%s — Z-Lab",
  },
  description: "Z-Lab 个人产品实验室：文件、翻译与模型工具。",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <header className="site-header">
          <Link className="brand" href="/" aria-label="回到 Z-Lab 首页">
            <span className="brand-mark">Z</span>
            <span>Z-LAB</span>
          </Link>
          <nav className="site-nav" aria-label="全站导航">
            <Link href="/#projects">项目</Link>
            <Link href="/#about">关于</Link>
            <a href="https://github.com/mai-hn" target="_blank" rel="noreferrer">
              GITHUB ↗
            </a>
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}
