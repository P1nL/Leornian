import { useSyncExternalStore } from 'react';
import { demoStore } from './demo-state.mjs';

export * from './LearningUI';
export const useDemo = () => useSyncExternalStore(demoStore.subscribe, demoStore.getSnapshot);
