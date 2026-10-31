import { useState } from "react";
import { explain, request } from "./api";
import type { ReviewCard, Session, Snapshot } from "./api";

const date = new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" });
const pendingKey = "leornian.pending-review.v1";
type Rating = "again" | "good" | "easy";
type Pending = { actorId: string; cardId: string; revision: number; rating: Rating; key: string };

function readPending(): Pending | null {
  try { return JSON.parse(localStorage.getItem(pendingKey) ?? "null") as Pending | null; }
  catch { return null; }
}

export function ReviewPanel({ session, snapshot, onUpdated }: {
  session: Session; snapshot: Snapshot; onUpdated: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [revealed, setRevealed] = useState<Record<string, number>>({});

  async function respond(card: ReviewCard, rating: Rating) {
    setBusy(true); setError("");
    const previous = readPending();
    const current = previous?.actorId === session.actor.id && previous.cardId === card.id
      && previous.revision === card.revision && previous.rating === rating ? previous : {
        actorId: session.actor.id, cardId: card.id, revision: card.revision, rating, key: crypto.randomUUID(),
      };
    localStorage.setItem(pendingKey, JSON.stringify(current));
    try {
      await request<ReviewCard>(`/v1/reviews/${card.id}/responses`, session.token, {
        method: "POST", headers: { "Idempotency-Key": current.key },
        body: JSON.stringify({ expected_revision: card.revision, rating }),
      });
      localStorage.removeItem(pendingKey); onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  async function toggle(card: ReviewCard) {
    setBusy(true); setError("");
    try {
      await request<ReviewCard>(`/v1/reviews/${card.id}/status`, session.token, {
        method: "POST", body: JSON.stringify({ expected_revision: card.revision,
          status: card.status === "paused" ? "scheduled" : "paused" }),
      });
      onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  return <section className="review-workspace" aria-labelledby="review-heading">
    <div className="section-heading"><h2 id="review-heading">给知识留一次回想</h2>
      <button className="text-button" onClick={onUpdated}>检查到期</button></div>
    <p className="tutor-description">完成本课后，第二天开始复习。先不看答案回想，再自评：需再练、记得、很熟悉分别安排 1、3、7 天后。自评不是评分，也不产生掌握度认证。</p>
    {snapshot.reviews.length === 0 ? <p className="empty">完成本课基础练习后，这里会出现复习安排。</p>
      : <ul className="review-list">{snapshot.reviews.map((card) => {
        const track = snapshot.tracks.find((item) => item.id === card.track_id);
        const goal = snapshot.goals.find((item) => item.id === track?.goal_id);
        const isRevealed = revealed[card.id] === card.revision;
        return <li key={card.id}>
          <div className="goal-heading"><h3>{goal?.title ?? "Python 入门课"}</h3>
            <span className="saved-state">{card.status === "paused" ? "已暂停" : card.due ? "现在可以复习" : "已安排"}</span></div>
          <p>{card.prompt}</p>
          <time dateTime={card.next_due_at}>计划时间：{date.format(new Date(card.next_due_at))}</time>
          {card.due && <div className="recall-actions">
            {!isRevealed ? <button className="text-button" disabled={busy}
              onClick={() => setRevealed((value) => ({ ...value, [card.id]: card.revision }))}>回想完了，查看要点</button> : <>
              <p>累加器从 0 开始；逐个处理数字，只累加能被 2 整除的数；空数组不进入循环，输出 0。</p>
              <div className="source-actions">
                <button className="text-button" disabled={busy} onClick={() => void respond(card, "again")}>还需再练 · 1 天后</button>
                <button className="text-button" disabled={busy} onClick={() => void respond(card, "good")}>记得要点 · 3 天后</button>
                <button className="text-button" disabled={busy} onClick={() => void respond(card, "easy")}>很熟悉 · 7 天后</button>
              </div>
            </>}
          </div>}
          <button className="text-button review-toggle" disabled={busy} onClick={() => void toggle(card)}>
            {card.status === "paused" ? "恢复复习安排" : "暂停这张复习卡"}
          </button>
        </li>;
      })}</ul>}
    {error && <p className="error" role="alert">{error}</p>}
  </section>;
}
