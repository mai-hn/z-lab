"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { DriveIcon, ModelIcon, RouteIcon } from "@/components/icons";
import { projects } from "@/lib/projects";

const iconMap = {
  "modal-drive": DriveIcon,
  "deepl-router": RouteIcon,
  "ai-model-checker": ModelIcon,
};

export function ProjectShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="project-layout">
      <aside className="project-rail" aria-label="项目导航">
        <span className="rail-label">PROJECTS</span>
        <div className="rail-links">
          {projects.map((project) => {
            const Icon = iconMap[project.id as keyof typeof iconMap];
            const active = pathname === project.href;
            return (
              <Link
                key={project.id}
                href={project.href}
                className={`rail-link accent-${project.accent}${active ? " active" : ""}`}
                aria-current={active ? "page" : undefined}
                title={project.name}
              >
                <Icon size={24} />
                <span>{project.shortName}</span>
                <small>{project.number}</small>
              </Link>
            );
          })}
        </div>
        <Link href="/#projects" className="rail-all">
          ALL
        </Link>
      </aside>
      <main className="project-main">{children}</main>
    </div>
  );
}
