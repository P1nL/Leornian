import { useId, useMemo, useState } from 'react';
import type { ComponentProps } from 'react';
import {
  AlgorithmBits, AlgorithmContainer, AlgorithmGeometry, AlgorithmGraph, AlgorithmGrid,
  AlgorithmIntervals, AlgorithmPlayer, AlgorithmRecursion, AlgorithmSequence,
} from './AlgorithmVisuals';
import {
  backtrackingDemo, binarySearchDemo, bitCountDemo, bracketDemo, breadthFirstDemo,
  closestPairDemo, gridPathsDemo, intervalDemo,
} from './algorithm-demos.mjs';

const fixedDemos = {
  graph: breadthFirstDemo(), grid: gridPathsDemo(), recursion: backtrackingDemo(),
  intervals: intervalDemo(), bits: bitCountDemo(), geometry: closestPairDemo(),
};
type ExampleKind = 'sequence' | 'container' | keyof typeof fixedDemos;
type StackScene = { input: ComponentProps<typeof AlgorithmSequence>['items']; items: ComponentProps<typeof AlgorithmContainer>['items'] };
type GraphScene = ComponentProps<typeof AlgorithmGraph> & { queue: ComponentProps<typeof AlgorithmContainer>['items'] };

export default function AlgorithmExample({ kind, active }: { kind: ExampleKind; active: boolean }) {
  const id = useId();
  const [target, setTarget] = useState(17);
  const [brackets, setBrackets] = useState('([])');
  const binary = useMemo(() => binarySearchDemo(target), [target]);
  const stack = useMemo(() => bracketDemo(brackets), [brackets]);
  switch (kind) {
    case 'sequence': return <>
      <div className="algo-example-options"><label htmlFor={id}>查找目标</label>
        <select id={id} value={target} onChange={(event) => setTarget(Number(event.target.value))}>
          <option value={17}>17 · 右侧</option><option value={2}>2 · 左侧</option>
          <option value={11}>11 · 中点</option><option value={12}>12 · 不存在</option>
        </select>
      </div>
      <AlgorithmPlayer<ComponentProps<typeof AlgorithmSequence>> key={target} {...binary} active={active} renderScene={(scene) => <AlgorithmSequence {...scene} />} />
    </>;
    case 'container': return <>
      <div className="algo-example-options"><label htmlFor={id}>括号输入</label>
        <select id={id} value={brackets} onChange={(event) => setBrackets(event.target.value)}>
          <option value="([])">([]) · 匹配</option><option value="([)]">([)] · 不匹配</option>
        </select>
      </div>
      <AlgorithmPlayer<StackScene> key={brackets} {...stack} active={active} renderScene={(scene) => <>
        <AlgorithmSequence items={scene.input} label="扫描中的括号序列" />
        <AlgorithmContainer items={scene.items} mode="stack" />
      </>} />
    </>;
    case 'graph': return <AlgorithmPlayer<GraphScene> {...fixedDemos.graph} active={active} renderScene={(scene) => <div className="algo-bfs-scene">
      <AlgorithmGraph nodes={scene.nodes} edges={scene.edges} label="BFS 图，按字母顺序访问相邻节点" />
      <AlgorithmContainer items={scene.queue} mode="queue" label="BFS 队列" />
    </div>} />;
    case 'grid': return <AlgorithmPlayer<ComponentProps<typeof AlgorithmGrid>> {...fixedDemos.grid} active={active} renderScene={(scene) => <AlgorithmGrid {...scene} />} />;
    case 'recursion': return <AlgorithmPlayer<ComponentProps<typeof AlgorithmRecursion>> {...fixedDemos.recursion} active={active} renderScene={(scene) => <AlgorithmRecursion {...scene} />} />;
    case 'intervals': return <AlgorithmPlayer<ComponentProps<typeof AlgorithmIntervals>> {...fixedDemos.intervals} active={active} renderScene={(scene) => <AlgorithmIntervals {...scene} />} />;
    case 'bits': return <AlgorithmPlayer<ComponentProps<typeof AlgorithmBits>> {...fixedDemos.bits} active={active} renderScene={(scene) => <AlgorithmBits {...scene} />} />;
    case 'geometry': return <AlgorithmPlayer<ComponentProps<typeof AlgorithmGeometry>> {...fixedDemos.geometry} active={active} renderScene={(scene) => <AlgorithmGeometry {...scene} />} />;
  }
}
