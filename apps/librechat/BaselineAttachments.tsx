import React, { useRef, useState } from 'react';
import { LearningAttachmentList } from './LearningAttachments';
import { nativeStore, nativeRequest } from './native-client.mjs';
import { useNative } from './NativeLearning';
import { defaultMaterialScope, prepareLearning, readIntake } from './native-intake.mjs';
import {
  continueMaterialFileUpload, materialFileIssue, newMaterialFileJournal,
} from './native-material-upload.mjs';

type Attachment = {
  id: string;
  name: string;
  digest: string;
  status: string;
  failed?: boolean;
  journal: Awaited<ReturnType<typeof newMaterialFileJournal>>;
};

const attachmentKey = (actorId: string, conversationId: string) =>
  `leornian.composer.attachments.v1:${actorId}:${conversationId}`;

function readAttachments(key: string): Attachment[] {
  try {
    const saved = JSON.parse(sessionStorage.getItem(key) ?? '[]');
    return Array.isArray(saved) ? saved : [];
  } catch { return []; }
}

export function useBaselineAttachments(conversationId: string | null, text: string) {
  const { snapshot } = useNative();
  const actorId = snapshot?.actor.id ?? null;
  const draft = actorId && !conversationId ? readIntake(sessionStorage, actorId) : null;
  const draftConversationId = draft?.attachment_draft ? draft.conversation_id : null;
  const currentConversationId = conversationId ?? draftConversationId;
  const storageKey = actorId && currentConversationId
    ? attachmentKey(actorId, currentConversationId) : null;
  const [, render] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const busy = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const attachments = storageKey ? readAttachments(storageKey) : [];

  async function upload(files: File[]) {
    if (busy.current || !files.length || !actorId) return;
    if (nativeStore.getSnapshot().snapshot?.actor.id !== actorId) return;
    const issue = files.map(materialFileIssue).find(Boolean);
    if (issue) { setError(issue); return; }
    busy.current = true; setUploading(true); setError('');
    try {
      let target = conversationId
        ? { goal_id: snapshot?.conversations.find((item) => item.id === conversationId)?.goal_id, conversation_id: conversationId }
        : null;
      if (!target) {
        const saved = readIntake(sessionStorage, actorId);
        const reusable = saved?.attachment_draft;
        const input = reusable ? saved.text : text.trim().length >= 3 ? text : '新学习计划';
        const result = await prepareLearning(input, {
          store: nativeStore, request: nativeRequest, storage: sessionStorage,
          materialScope: saved && saved.text === input ? saved.material_scope ?? null : defaultMaterialScope,
          attachmentDraft: true,
        });
        target = result.conversation
          ? { goal_id: result.conversation.goal_id, conversation_id: result.conversation.id } : null;
      }
      if (!target?.goal_id || !target.conversation_id) throw new Error('当前学习计划尚未就绪，请稍后重新选择资料。');
      const key = attachmentKey(actorId, target.conversation_id);
      const persist = (attachment: Attachment) => {
        if (nativeStore.getSnapshot().snapshot?.actor.id !== actorId) throw new Error('学习身份已切换，原上传保留。');
        const entries = readAttachments(key);
        const index = entries.findIndex((item) => item.id === attachment.id);
        if (index < 0) entries.push(attachment);
        else entries[index] = attachment;
        sessionStorage.setItem(key, JSON.stringify(entries));
        render((value) => value + 1);
      };
      for (const file of files) {
        const journal = await newMaterialFileJournal(file, target.goal_id);
        let attachment = readAttachments(key).find((item) => item.digest === journal.digest)
          ?? { id: crypto.randomUUID(), name: file.name, digest: journal.digest, status: '等待上传', journal };
        if (attachment.journal.stage === 'done') continue;
        persist(attachment);
        try {
          await continueMaterialFileUpload(file, attachment.journal, {
            actorId, store: nativeStore, request: nativeRequest,
            persist: (next: Attachment['journal']) => {
              attachment = { ...attachment, journal: next, failed: false }; persist(attachment);
            },
            progress: (status: string) => {
              attachment = { ...attachment, status, failed: false }; persist(attachment);
            },
          });
        } catch (cause) {
          attachment = { ...attachment, status: '上传待恢复 · 重新选择同一文件继续', failed: true };
          persist(attachment);
          throw cause;
        }
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      busy.current = false; setUploading(false);
    }
  }

  return {
    uploading,
    pending: attachments.some((attachment) => attachment.journal.stage !== 'done'),
    open: () => inputRef.current?.click(),
    content: <>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".pdf,.docx,.txt,.md,.markdown,.html,.htm,.png,.jpg,.jpeg"
        className="sr-only"
        aria-label="选择学习资料"
        onChange={(event) => {
          const files = Array.from(event.currentTarget.files ?? []);
          event.currentTarget.value = '';
          void upload(files);
        }}
      />
      <LearningAttachmentList attachments={attachments.map((item) => ({
        ...item, ready: item.journal.stage === 'done',
      }))} error={error} />
    </>,
  };
}
