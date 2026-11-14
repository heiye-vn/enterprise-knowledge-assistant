import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { init, use } from 'echarts/core';
import type { EChartsType } from 'echarts/core';
import { GraphChart } from 'echarts/charts';
import { AriaComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { LabelLayout } from 'echarts/features';
import { buildGraphOption } from './graph-chart';
import { createGraphViewportController } from './graph-viewport';
import type { GraphView } from './graph-model';

use([GraphChart, TooltipComponent, AriaComponent, LabelLayout, CanvasRenderer]);
export type GraphChartHandle = { zoom: (factor: number) => void; fit: () => void };
type Props = {
  view: GraphView; selectedNodeId?: string; selectedEdgeId?: string;
  onNode: (id: string) => void; onEdge: (id: string) => void;
};

export default forwardRef<GraphChartHandle, Props>(function EChartsGraph({ view, selectedNodeId, selectedEdgeId, onNode, onEdge }, ref) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<EChartsType | null>(null);
  const viewport = useRef<ReturnType<typeof createGraphViewportController> | null>(null);
  const handlers = useRef({ onNode, onEdge });
  handlers.current = { onNode, onEdge };
  const [error, setError] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(() => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReducedMotion(media.matches);
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);

  useEffect(() => {
    if (!host.current) return;
    let instance: EChartsType;
    try {
      instance = init(host.current, undefined, { renderer: 'canvas' });
    } catch {
      setError(true); return;
    }
    chart.current = instance;
    const controller = createGraphViewportController(instance);
    viewport.current = controller;
    instance.on('rendered', controller.onRendered);
    instance.on('click', params => {
      const id = (params.data as { id?: string })?.id;
      if (!id) return;
      (params.dataType === 'edge' ? handlers.current.onEdge : handlers.current.onNode)(id);
      queueMicrotask(() => {
        if (!instance.isDisposed()) instance.dispatchAction({ type: 'select', seriesIndex: 0, dataType: params.dataType, dataIndex: params.dataIndex });
      });
    });
    const observer = new ResizeObserver(() => {
      instance.resize({ animation: { duration: 0 } });
      controller.requestAutoFit();
    });
    observer.observe(host.current);
    return () => { controller.dispose(); viewport.current = null; observer.disconnect(); instance.dispose(); chart.current = null; };
  }, []);

  useEffect(() => {
    const instance = chart.current;
    if (!instance) return;
    viewport.current?.requestAutoFit();
    instance.setOption(buildGraphOption(view, reducedMotion), { notMerge: true });
    if (reducedMotion) viewport.current?.fit();
  }, [view, reducedMotion]);

  useEffect(() => {
    const instance = chart.current;
    if (!instance) return;
    instance.dispatchAction({ type: 'downplay', seriesIndex: 0 });
    instance.dispatchAction({ type: 'unselect', seriesIndex: 0, dataIndex: view.nodes.map((_, index) => index) });
    instance.dispatchAction({ type: 'unselect', seriesIndex: 0, dataType: 'edge', dataIndex: view.edges.map((_, index) => index) });
    const dataType = selectedEdgeId ? 'edge' : 'node';
    const dataIndex = selectedEdgeId ? view.edges.findIndex(edge => edge.id === selectedEdgeId) : view.nodes.findIndex(node => node.id === selectedNodeId);
    if (dataIndex < 0) return;
    instance.dispatchAction({ type: 'select', seriesIndex: 0, dataType, dataIndex });
    instance.dispatchAction({ type: 'highlight', seriesIndex: 0, dataType, dataIndex });
  }, [selectedNodeId, selectedEdgeId, view, reducedMotion]);

  useImperativeHandle(ref, () => ({
    zoom(factor) { viewport.current?.zoom(factor); },
    fit() { viewport.current?.fit(); },
  }), []);

  return <div ref={host} className="echarts-graph" role="img" aria-label="知识关联图，可在下方节点列表中使用键盘选择实体">{error && <p className="graph-render-error">图谱画布暂时无法加载，可使用下方节点与关系列表查看依据。</p>}</div>;
});
