import { ProjectShell } from "@/components/project-shell";

export default function ProjectsLayout({ children }: { children: React.ReactNode }) {
  return <ProjectShell>{children}</ProjectShell>;
}
