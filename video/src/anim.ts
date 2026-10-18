import {createContext, useContext} from 'react';
import {Easing, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';

// Stills (thumbnail / X cards) render scene components in their fully-animated end state.
export const StaticCtx = createContext(false);

export const useT = (): number => {
  const frame = useCurrentFrame();
  return useContext(StaticCtx) ? 100000 : frame;
};

export const useEnter = (delayFrames = 0, damping = 18): number => {
  const t = useT();
  const {fps} = useVideoConfig();
  return spring({frame: t - delayFrames, fps, config: {damping, mass: 0.8}});
};

export const progress = (t: number, start: number, dur: number): number =>
  interpolate(t, [start, start + dur], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic),
  });

export const slideUp = (p: number, dist = 40): React.CSSProperties => ({
  opacity: p,
  transform: `translateY(${(1 - p) * dist}px)`,
});
