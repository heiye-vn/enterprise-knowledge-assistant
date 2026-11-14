import type { ComposeOption, EChartsType } from 'echarts/core';
import type { GraphSeriesOption } from 'echarts/charts';
import type { AriaComponentOption, TooltipComponentOption } from 'echarts/components';
import { graphKinds } from './graph-data.ts';
import type { GraphView } from './graph-model';
import { getGraphViewportFit } from './graph-model.ts';

export type KnowledgeGraphOption = ComposeOption<GraphSeriesOption | TooltipComponentOption | AriaComponentOption>;

export function buildGraphOption(view: GraphView, reducedMotion = false): KnowledgeGraphOption {
  const nodesById = new Map(view.nodes.map(node => [node.id, node]));
  const edgesById = new Map(view.edges.map(edge => [edge.id, edge]));
  return {
    animation: !reducedMotion,
    animationDurationUpdate: reducedMotion ? 0 : 250,
    aria: { enabled: true, label: { description: `知识关联图，当前显示 ${view.nodes.length} 个节点、${view.edges.length} 条关系。可使用图谱下方的节点列表选择实体、展开关联和查看原文。` } },
    tooltip: {
      trigger: 'item', renderMode: 'richText', confine: true,
      backgroundColor: '#ffffff', borderColor: '#dce5f1', padding: [12, 15],
      textStyle: { color: '#425b7d', fontSize: 12, lineHeight: 22 },
      formatter: params => {
        const item = Array.isArray(params) ? params[0] : params;
        const id = (item.data as { id?: string })?.id;
        if (item.dataType === 'edge') {
          const edge = id ? edgesById.get(id) : undefined;
          return edge ? `${nodesById.get(edge.source)?.title}\n${edge.label} → ${nodesById.get(edge.target)?.title}\n点击查看关系与依据` : '';
        }
        const node = id ? nodesById.get(id) : undefined;
        return node ? `${node.title}\n${graphKinds.find(kind => kind.id === node.kind)?.label}\n${node.detail}\n点击选择，可展开关联和查看原文` : '';
      },
    },
    series: [{
      id: 'knowledge', type: 'graph', layout: 'force', roam: true, draggable: !reducedMotion,
      selectedMode: 'single', scaleLimit: { min: 0.08, max: 3 },
      left: '12%', right: '12%', top: '12%', bottom: '18%',
      force: { initLayout: 'circular', repulsion: 650, gravity: 0.06, edgeLength: [105, 170], friction: 0.65, layoutAnimation: !reducedMotion },
      categories: graphKinds.map(kind => ({ name: kind.label, symbol: kind.symbol, itemStyle: { color: kind.color } })),
      data: view.nodes.map(node => {
        const kind = graphKinds.find(kind => kind.id === node.kind)!;
        return {
          id: node.id, name: node.title, category: kind.label, symbol: kind.symbol,
          symbolSize: node.kind === 'document' ? [36, 30] : 30,
          itemStyle: { color: kind.color, borderColor: '#ffffff', borderWidth: 3, shadowBlur: 8, shadowColor: `${kind.color}25` },
          label: { show: view.nodes.length <= 24 || view.matchedIds.includes(node.id) },
        };
      }),
      links: view.edges.map(edge => ({
        id: edge.id, source: edge.source, target: edge.target,
        label: { formatter: edge.label },
        emphasis: { label: { show: true, color: '#355777', backgroundColor: '#ffffffed', padding: [4, 7], borderRadius: 4 } },
      })),
      edgeSymbol: ['none', 'arrow'], edgeSymbolSize: [0, 7],
      lineStyle: { color: '#adc1d9', width: 1.5, curveness: 0.08, opacity: 0.8 },
      label: { position: 'bottom', distance: 9, color: '#425b7d', fontSize: 12, width: 150, overflow: 'truncate', backgroundColor: '#ffffffdf', padding: [3, 5], borderRadius: 4 },
      edgeLabel: { show: false, fontSize: 11 },
      labelLayout: { hideOverlap: true },
      emphasis: { focus: 'adjacency', scale: 1.2, label: { show: true }, lineStyle: { color: '#467dc5', width: 2.5, opacity: 1 } },
      select: { itemStyle: { borderColor: '#173d77', borderWidth: 3 }, label: { show: true, fontWeight: 600 }, edgeLabel: { show: true, color: '#355777', backgroundColor: '#ffffffed', padding: [4, 7], borderRadius: 4 }, lineStyle: { color: '#467dc5', width: 2.5 } },
      blur: { itemStyle: { opacity: 0.3 }, lineStyle: { opacity: 0.15 }, label: { opacity: 0.3 } },
    }],
  };
}

export function fitGraphToCanvas(instance: EChartsType) {
  if (instance.getWidth() <= 0 || instance.getHeight() <= 0) return;
  instance.dispatchAction({ type: 'hideTip' });
  const points: number[][] = [];
  for (const element of instance.getZr().storage.getDisplayList(true)) {
    if (element.ignore || element.invisible) continue;
    const bounds = element.getBoundingRect().clone();
    const transform = element.getComputedTransform();
    if (transform) bounds.applyTransform(transform);
    points.push([bounds.x, bounds.y], [bounds.x + bounds.width, bounds.y + bounds.height]);
  }
  const fit = getGraphViewportFit(points, instance.getWidth(), instance.getHeight());
  instance.dispatchAction({ type: 'graphRoam', seriesId: 'knowledge', zoom: fit.zoom, originX: fit.origin[0], originY: fit.origin[1] });
  instance.dispatchAction({ type: 'graphRoam', seriesId: 'knowledge', dx: fit.pan[0], dy: fit.pan[1] });
}
