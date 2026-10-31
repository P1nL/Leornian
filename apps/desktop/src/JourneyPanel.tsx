import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { explain, request } from "./api";
import type { Attempt, LessonView, Session, Snapshot, Track } from "./api";

type Draft = { actorId: string; trackId: string; key: string; code: string };
const draftKey = "leornian.submission.v1";

function readDraft(): Draft | null {
  try { return JSON.parse(localStorage.getItem(draftKey) ?? "null") as Draft | null; }
  catch { return null; }
}

export function JourneyPanel({ session, snapshot, onUpdated }: {
  session: Session; snapshot: Snapshot; onUpdated: () => void;
}) {
  const [goalId, setGoalId] = useState("");
  const [lesson, setLesson] = useState<LessonView | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const goal = snapshot.goals.find((item) => item.id === goalId) ?? snapshot.goals[0];
  const track = snapshot.tracks.find((item) => item.goal_id === goal?.id);
  const attempts = snapshot.attempts.filter((item) => item.track_id === track?.id);
  const pending = attempts.some((item) => item.status === "queued");

  useEffect(() => {
    setLesson(null); setCode(""); setError("");
    if (!track || track.status === "draft") return;
    const controller = new AbortController();
    void request<LessonView>(`/v1/tracks/${track.id}/lesson`, session.token, {
      signal: controller.signal,
    }).then((next) => {
      if (controller.signal.aborted) return;
      setLesson(next);
      const draft = readDraft();
      setCode(draft?.actorId === session.actor.id && draft.trackId === track.id
        ? draft.code : next.exercise.starter_code);
    }).catch((problem) => {
      if (!controller.signal.aborted) setError(explain(problem));
    });
    return () => controller.abort();
  }, [track?.id, track?.status === "draft", session.token]);

  async function plan() {
    if (!goal) return;
    setBusy(true); setError("");
    try {
      await request<Track>("/v1/tracks", session.token, {
        method: "POST", body: JSON.stringify({ goal_id: goal.id, course_version: "python-even-sum.v1" }),
      });
      onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  async function confirm() {
    if (!track) return;
    setBusy(true); setError("");
    try {
      await request<Track>(`/v1/tracks/${track.id}/confirm`, session.token, {
        method: "POST", body: JSON.stringify({ expected_revision: track.revision }),
      });
      onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!track) return;
    setBusy(true); setError("");
    const saved = readDraft();
    const draft = saved?.actorId === session.actor.id && saved.trackId === track.id
      && saved.code === code ? saved : {
        actorId: session.actor.id, trackId: track.id, key: crypto.randomUUID(), code,
      };
    localStorage.setItem(draftKey, JSON.stringify(draft));
    try {
      await request<Attempt>(`/v1/tracks/${track.id}/submissions`, session.token, {
        method: "POST", headers: { "Idempotency-Key": draft.key }, body: JSON.stringify({ code }),
      });
      localStorage.removeItem(draftKey);
      onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  return <section className="journey-workspace" aria-labelledby="journey-heading">
    <h2 id="journey-heading">完成一节 Python 入门课</h2>
    <p className="tutor-description">固定入门样例：循环、条件与累加。不是根据任意目标生成的计划，也不是动态审核题包。</p>
    {!goal ? <p className="empty">先保存目标，再把这节课加入你的学习空间。</p> : <>
      <label htmlFor="journey-goal">关联目标</label>
      <select id="journey-goal" value={goal.id} disabled={busy}
        onChange={(event) => setGoalId(event.target.value)}>
        {snapshot.goals.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
      </select>
      {!track ? <button className="primary journey-action" disabled={busy} onClick={() => void plan()}>查看入门计划草案</button>
        : track.status === "draft" ? <div className="plan-draft">
          <h3>计划草案 · 版本 {track.revision}</h3>
          <p>一个课时：读取 JSON 数组 → 筛选偶数 → 累加 → 提交代码。确认后解锁正文与练习。</p>
          <button className="primary" disabled={busy} onClick={() => void confirm()}>确认这一版计划</button>
        </div> : <>
          <p className="saved-state">{track.status === "completed" ? "本课基础练习已完成" : "计划已确认 · 等待完成练习"}</p>
          {lesson ? <>
            <article className="lesson-body"><h3>{lesson.lesson.title}</h3><p>{lesson.lesson.body}</p></article>
            <h3>{lesson.exercise.title}</h3><p className="exercise-prompt">{lesson.exercise.prompt}</p>
            <small className="provenance">{lesson.exercise.provenance}</small>
            <form onSubmit={submit} className="code-form">
              <label htmlFor="exercise-code">Python 代码</label>
              <textarea id="exercise-code" className="code-input" spellCheck={false} rows={10}
                value={code} maxLength={12000} required disabled={busy}
                onChange={(event) => setCode(event.target.value)} />
              <div className="form-footer"><p>在无网络、无宿主文件的隔离容器中运行；结果由服务端评测。</p>
                <button className="primary" disabled={busy || pending || !code.trim()}>
                  {pending ? "等待隔离执行结果…" : busy ? "正在提交…" : "提交并评测"}
                </button>
              </div>
            </form>
          </> : <p className="empty">正在读取已确认课时…</p>}
          {attempts.length > 0 && <div className="attempt-history" aria-label="作答与反馈">
            {attempts.slice(0, 5).map((attempt) => <article key={attempt.id}>
              <h3>{attempt.status === "queued" ? "等待 Runner 处理" : attempt.status === "passed"
                ? "本次基础练习通过" : attempt.status === "error" ? "执行环境错误" : "还没有通过"}</h3>
              <p>{attempt.feedback ?? "任务已持久保存。Runner 未运行时会保持等待，不会假装成功。"}</p>
            </article>)}
          </div>}
        </>}
      {error && <p className="error" role="alert">{error}</p>}
    </>}
  </section>;
}
