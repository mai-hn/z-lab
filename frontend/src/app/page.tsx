import Link from "next/link";
import { ArrowIcon, CheckIcon, DriveIcon, ModelIcon, RouteIcon } from "@/components/icons";
import { projects } from "@/lib/projects";

const icons = [DriveIcon, RouteIcon, ModelIcon];

export default function HomePage() {
  return (
    <main>
      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">INDEPENDENT PRODUCT LAB · SHANGHAI</p>
          <h1>
            把想法做成
            <br />
            <span>真正可用</span>的工具。
          </h1>
          <p className="hero-lead">
            这里是 Z-Lab，一个专注于小而可靠产品的独立实验室。这里收录文件、翻译和 AI
            基础设施方向的长期实验。
          </p>
          <div className="hero-actions">
            <Link className="button button-dark" href="#projects">
              查看项目 <ArrowIcon />
            </Link>
            <a className="text-link" href="https://github.com/mai-hn" target="_blank" rel="noreferrer">
              GITHUB ↗
            </a>
          </div>
        </div>
        <div className="hero-orbit" aria-label="三个项目构成的工具系统">
          <div className="orbit-ring ring-one" />
          <div className="orbit-ring ring-two" />
          {projects.map((project, index) => {
            const Icon = icons[index];
            return (
              <Link
                className={`orbit-node orbit-${index + 1} accent-${project.accent}`}
                href={project.href}
                key={project.id}
              >
                <Icon size={34} />
                <b>{project.number}</b>
              </Link>
            );
          })}
          <div className="orbit-core">Z</div>
          <span className="orbit-note">BUILD · TEST · SHIP</span>
        </div>
      </section>

      <section className="projects-section" id="projects">
        <div className="section-heading">
          <div>
            <p className="eyebrow">SELECTED PROJECTS / 2026</p>
            <h2>三个工具，一个工作台。</h2>
          </div>
          <p>
            每个项目保持独立边界，共享同一套界面、部署方式和 Python 服务入口。下一项工具只需注册配置，
            无需重做整个网站。
          </p>
        </div>
        <div className="project-list">
          {projects.map((project, index) => {
            const Icon = icons[index];
            return (
              <article className={`project-row accent-${project.accent}`} key={project.id}>
                <span className="project-number">{project.number}</span>
                <div className="project-symbol">
                  <Icon size={44} />
                </div>
                <div className="project-copy">
                  <div className="tag">{project.tag}</div>
                  <h3>{project.name}</h3>
                  <p>{project.longDescription}</p>
                  <div className="capability-list">
                    {project.capabilities.map((item) => (
                      <span key={item}>
                        <CheckIcon size={15} /> {item}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="project-meta">
                  {project.stack.map((item) => (
                    <code key={item}>{item}</code>
                  ))}
                  <Link className="circle-link" href={project.href} aria-label={`打开 ${project.name}`}>
                    <ArrowIcon size={25} />
                  </Link>
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <section className="about-section" id="about">
        <div className="about-index">/ 04</div>
        <div>
          <p className="eyebrow">ABOUT THE LAB</p>
          <h2>
            为真实问题写代码，
            <br />
            为长期使用做设计。
          </h2>
        </div>
        <div className="about-copy">
          <p>
            我喜欢透明、可部署、可维护的工具。没有多余抽象，也不把复杂度藏在用户看不见的地方。
          </p>
          <dl>
            <div>
              <dt>03</dt>
              <dd>ACTIVE TOOLS</dd>
            </div>
            <div>
              <dt>01</dt>
              <dd>UNIFIED STACK</dd>
            </div>
            <div>
              <dt>∞</dt>
              <dd>NEXT IDEAS</dd>
            </div>
          </dl>
        </div>
      </section>

      <footer className="site-footer">
        <span>© 2026 Z-LAB</span>
        <span>BUILT WITH NEXT.JS + PYTHON</span>
        <a href="#top">回到顶部 ↑</a>
      </footer>
    </main>
  );
}
