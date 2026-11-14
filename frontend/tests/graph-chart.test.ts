import assert from 'node:assert/strict';
import test from 'node:test';
import { init, use } from 'echarts/core.js';
import { GraphChart } from 'echarts/charts.js';
import { SVGRenderer } from 'echarts/renderers.js';
import { AriaComponent, TooltipComponent } from 'echarts/components.js';
import { LabelLayout } from 'echarts/features.js';
import { graphKinds, graphScenarios } from '../src/graph-data.ts';
import { buildGraphView } from '../src/graph-model.ts';
import { buildGraphOption, fitGraphToCanvas } from '../src/graph-chart.ts';
import { createGraphViewportController } from '../src/graph-viewport.ts';

use([GraphChart, SVGRenderer, AriaComponent, TooltipComponent, LabelLayout]);
const kinds = graphKinds.map(kind => kind.id);

test('real ECharts rendering keeps expanded graph nodes inside wide and narrow canvases', () => {
  for (const scenario of graphScenarios) for (const width of [1100, 330]) {
    const height = width < 500 ? 350 : 460;
    const view = buildGraphView(scenario.graph, { rootIds: scenario.rootIds, expandedIds: scenario.graph.nodes.map(node => node.id), kinds, search: '' });
    const chart = init(null, undefined, { renderer: 'svg', ssr: true, width, height });
    try {
      chart.setOption(buildGraphOption(view, true));
      fitGraphToCanvas(chart);
      const data = chart.getModel().getSeriesByIndex(0).getData();
      for (let index = 0; index < data.count(); index++) {
        const pixel = chart.convertToPixel({ seriesIndex: 0 }, data.getItemLayout(index));
        assert(pixel.every(Number.isFinite));
        assert(pixel[0] >= 50 && pixel[0] <= width - 50);
        assert(pixel[1] >= 30 && pixel[1] <= height - 30);
      }
    } finally { chart.dispose(); }
  }
});

test('real ECharts force graph retains a dragged node position', () => {
  const scenario = graphScenarios[0];
  const view = buildGraphView(scenario.graph, { rootIds: scenario.rootIds, expandedIds: [], kinds, search: '' });
  const chart = init(null, undefined, { renderer: 'svg', ssr: true, width: 1100, height: 400 });
  try {
    chart.setOption(buildGraphOption(view, false));
    const index = view.nodes.findIndex(node => node.id === scenario.rootIds[0]);
    const node = chart.getModel().getSeriesByIndex(0).getData().getItemGraphicEl(index);
    assert.equal(node.childAt(0).draggable, true);
    node.x += 100; node.y += 50;
    const destination = [node.x, node.y];
    node.trigger('drag', { offsetX: node.x, offsetY: node.y });
    assert.deepEqual([node.x, node.y], destination);
    node.trigger('dragend', {});
  } finally { chart.dispose(); }
});

test('a selected relationship label stays visible without pointer hover', () => {
  const scenario = graphScenarios[0];
  const view = buildGraphView(scenario.graph, { rootIds: scenario.rootIds, expandedIds: [], kinds, search: '' });
  const chart = init(null, undefined, { renderer: 'svg', ssr: true, width: 1100, height: 400 });
  try {
    chart.setOption(buildGraphOption(view, true));
    chart.dispatchAction({ type: 'select', seriesIndex: 0, dataType: 'edge', dataIndex: 0 });
    chart.getZr().animation.update();
    assert(chart.renderToSVGString().includes(view.edges[0].label));
  } finally { chart.dispose(); }
});

function createExpandedChart() {
  const scenario = graphScenarios[0];
  const view = buildGraphView(scenario.graph, { rootIds: scenario.rootIds, expandedIds: scenario.graph.nodes.map(node => node.id), kinds, search: '' });
  const chart = init(null, undefined, { renderer: 'svg', ssr: true, width: 330, height: 350 });
  chart.setOption(buildGraphOption(view, true));
  return chart;
}

test('manual fit adjusts the current viewport immediately without rebuilding or moving graph nodes', () => {
  const chart = createExpandedChart();
  const viewport = createGraphViewportController(chart);
  try {
    const model = chart.getModel().getSeriesByIndex(0);
    const positions = Array.from({ length: model.getData().count() }, (_, index) => [...model.getData().getItemLayout(index)]);
    viewport.fit();
    assert.equal(chart.getModel().getSeriesByIndex(0), model);
    assert(chart.getOption().series[0].zoom < 1);
    assert.deepEqual(Array.from({ length: model.getData().count() }, (_, index) => [...model.getData().getItemLayout(index)]), positions);
  } finally { viewport.dispose(); chart.dispose(); }
});

test('manual fit cancels a pending auto fit so later frames cannot shrink the viewport again', context => {
  context.mock.timers.enable({ apis: ['setTimeout'] });
  const chart = createExpandedChart();
  const viewport = createGraphViewportController(chart);
  try {
    viewport.requestAutoFit();
    viewport.fit();
    const zoom = chart.getOption().series[0].zoom;
    viewport.onRendered();
    context.mock.timers.tick(3000);
    assert.equal(chart.getOption().series[0].zoom, zoom);
    // A manual zoom after fitting must also remain in place.
    chart.dispatchAction({ type: 'graphRoam', seriesId: 'knowledge', zoom: 1.5, originX: 165, originY: 175 });
    const manualZoom = chart.getOption().series[0].zoom;
    viewport.onRendered();
    context.mock.timers.tick(3000);
    assert.equal(chart.getOption().series[0].zoom, manualZoom);
  } finally { viewport.dispose(); chart.dispose(); }
});

test('manual zoom takes precedence over a pending automatic fit', context => {
  context.mock.timers.enable({ apis: ['setTimeout'] });
  const chart = createExpandedChart();
  const viewport = createGraphViewportController(chart);
  try {
    viewport.requestAutoFit();
    viewport.zoom(1.2);
    const zoom = chart.getOption().series[0].zoom;
    assert(Math.abs(zoom - 1.2) < 0.00001);
    viewport.onRendered();
    context.mock.timers.tick(3000);
    assert.equal(chart.getOption().series[0].zoom, zoom);
  } finally { viewport.dispose(); chart.dispose(); }
});

test('new graph changes can request automatic fitting again after a manual fit', context => {
  context.mock.timers.enable({ apis: ['setTimeout'] });
  const chart = createExpandedChart();
  const viewport = createGraphViewportController(chart);
  try {
    viewport.fit();
    chart.dispatchAction({ type: 'graphRoam', seriesId: 'knowledge', zoom: 1.5, originX: 165, originY: 175 });
    const before = chart.getOption().series[0].zoom;
    viewport.requestAutoFit();
    context.mock.timers.tick(119);
    assert.equal(chart.getOption().series[0].zoom, before);
    viewport.onRendered();
    context.mock.timers.tick(119);
    assert.equal(chart.getOption().series[0].zoom, before);
    context.mock.timers.tick(1);
    assert(chart.getOption().series[0].zoom < before);
  } finally { viewport.dispose(); chart.dispose(); }
});
