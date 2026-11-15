import type { EChartsType } from 'echarts/core';
import { fitGraphToCanvas } from './graph-chart.ts';

export function createGraphViewportController(instance: EChartsType) {
  let pending = false;
  let disposed = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  function cancelAutoFit() {
    pending = false;
    clearTimeout(timer);
    timer = undefined;
  }
  function schedule() {
    if (!pending || disposed || instance.isDisposed()) return;
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (!pending || disposed || instance.isDisposed()) return;
      pending = false;
      timer = undefined;
      fitGraphToCanvas(instance);
    }, 120);
  }
  instance.on('graphroam', cancelAutoFit);
  return {
    resize(width: number, height: number) {
      // Hidden or detached hosts can report zero size before React tears down the observer.
      if (disposed || instance.isDisposed() || width <= 0 || height <= 0) return;
      instance.resize({ width, height, animation: { duration: 0 } });
      pending = true;
      schedule();
    },
    requestAutoFit() { if (!disposed) { pending = true; schedule(); } },
    onRendered: schedule,
    fit() {
      cancelAutoFit();
      if (!disposed && !instance.isDisposed()) fitGraphToCanvas(instance);
    },
    zoom(factor: number) {
      cancelAutoFit();
      if (!disposed && !instance.isDisposed()) instance.dispatchAction({ type: 'graphRoam', seriesId: 'knowledge', zoom: factor, originX: instance.getWidth() / 2, originY: instance.getHeight() / 2 });
    },
    dispose() { cancelAutoFit(); disposed = true; instance.off('graphroam', cancelAutoFit); },
  };
}
