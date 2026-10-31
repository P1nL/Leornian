import type { GeneratedLesson, Source } from "./api";

export function LessonReader({ lesson, sources }: { lesson: GeneratedLesson; sources: Source[] }) {
  const stale = lesson.sources.some((ref) => !sources.some((source) =>
    source.id === ref.source_id && source.revision === ref.revision && source.usable));
  return <article className="generated-lesson" aria-label={lesson.document.title}>
    <h3>{lesson.document.title}</h3>
    <p className="provenance">计划版本 {lesson.plan_revision} · 节点 {lesson.node_key} · 模型生成正文，未独立事实审核</p>
    {stale && <p className="plan-version-note">引用来源已变化或失效。正文作为历史保留，不代表当前内容仍获准使用。</p>}
    <p>{lesson.document.introduction}</p>
    {lesson.document.sections.map((section, index) => <section key={index}>
      <h4>{section.heading}</h4><p className="lesson-explanation">{section.explanation}</p>
      {section.code_example && <figure className="lesson-code">
        <figcaption>示例代码 · 仅阅读，未执行或测试</figcaption>
        <pre><code>{section.code_example}</code></pre>
      </figure>}
      <ul className="plan-citations">{section.source_refs.map((ref) => {
        const material = lesson.sources.find((source) => source.source_id === ref.source_id && source.revision === ref.revision);
        return material && <li key={`${ref.source_id}:${ref.revision}`}><details>
          <summary>{material.title} · 来源版本 {material.revision}</summary>
          <a href={material.source_url} target="_blank" rel="noreferrer noopener">打开原文链接</a>
          <p className="source-excerpt">{material.excerpt}</p>
          <small>学习者提供的原始摘录；版本与引用可追溯，不代表模型解释已经独立验证。</small>
        </details></li>;
      })}</ul>
    </section>)}
    <section className="lesson-recall"><h4>停一下，试着回想</h4>
      <ul>{lesson.document.recall_prompts.map((prompt, index) => <li key={index}>{prompt}</li>)}</ul>
      <p className="provenance">这些是回想问题，不收集评分，也不标记课程完成。</p>
    </section>
  </article>;
}
