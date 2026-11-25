import { LoaderCircle, Paperclip, TriangleAlert } from 'lucide-react';

export type LearningAttachment = {
  id: string; name: string; status: string; ready: boolean; failed?: boolean;
};

export function LearningAttachmentList({ attachments, error = '' }: {
  attachments: LearningAttachment[]; error?: string;
}) {
  return <>
    {!!attachments.length && <ul className="baseline-attachments" aria-label="已选择的学习资料" aria-live="polite">
      {attachments.map((attachment) => <li key={attachment.id} title={attachment.name}>
        {attachment.failed ? <TriangleAlert size={14} aria-hidden />
          : attachment.ready ? <Paperclip size={14} aria-hidden />
            : <LoaderCircle size={14} className="animate-spin motion-reduce:animate-none" aria-hidden />}
        <span className="baseline-attachment-name">{attachment.name}</span>
        <span className="baseline-attachment-status">{attachment.status}</span>
      </li>)}
    </ul>}
    {error && <p className="baseline-attachment-error" role="alert">{error}</p>}
  </>;
}
