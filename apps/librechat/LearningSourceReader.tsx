import type { components } from '@leornian/api-contracts';
import { Notice } from './LearningUI';

type Source = components['schemas']['CompositionSourceView'];
function sourceLocation(source: Source) {
  const location = source.location;
  if (location?.location_basis === 'image_region') return `图片区域 ${location.number}`;
  if (location?.location_basis === 'document_part') {
    return `文档部件 ${location.number}${location.original_part ? `（${location.original_part}）` : ''}`;
  }
  const page = location?.number ?? source.block?.source_page;
  return page ? `第 ${page} 页` : '';
}

export function LearningSourceReader({ content, error = '' }: { content: Source | null; error?: string }) {
  const location = content ? sourceLocation(content) : '';
  return <div className="demo-reader-content">
    {error ? <Notice>当前无法读取此引用：{error}。不改读其他版本。</Notice>
      : !content ? <Notice>正在重新核对来源权限…</Notice>
      : content.block ? <>
        <p className="demo-muted">固定版本 {content.block.ref.document_revision} · {content.block.section_path.join(' / ')}
          {location ? ` · ${location}` : ''}</p>
        <mark tabIndex={-1}>{content.block.text}</mark>
      </> : <mark tabIndex={-1}>{content.excerpt}</mark>}
  </div>;
}
