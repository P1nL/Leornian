import { useLayoutEffect, useMemo, useRef } from 'react';
import type { components } from '@leornian/api-contracts';
import { generationMessages } from './generation-relay';
import { relayView } from './question-bank-relay/view.mjs';
import { createRelayScore } from './question-bank-relay/score.mjs';
import { mountRelay } from './question-bank-relay/script.js';
import * as bundledMotion from './question-bank-relay/vendor/gsap.min.js';
import './question-bank-relay/style.css';

type Report = components['schemas']['GenerationReport'];

export default function QuestionBankRelay({ report, executable }: { report: Report; executable: boolean }) {
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<ReturnType<typeof mountRelay> | null>(null);
  const score = useMemo(() => createRelayScore(generationMessages(report, executable), executable), [report, executable]);
  useLayoutEffect(() => {
    const element = host.current!;
    return () => { scene.current?.destroy(); scene.current = null; element.replaceChildren(); };
  }, []);
  useLayoutEffect(() => {
    if (scene.current) { scene.current.update(score); return; }
    const element = host.current!;
    element.innerHTML = relayView;
    const gsap = Reflect.get(bundledMotion, 'gsap') ?? Reflect.get(window, 'gsap');
    scene.current = mountRelay(element.firstElementChild, score, gsap);
  }, [score]);
  return <div className="bank-relay" ref={host} />;
}
