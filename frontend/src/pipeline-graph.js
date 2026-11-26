const DEFAULT_OUTCOME = "SUCCESS";

export function normalizePipelineSteps(steps) {
  if (!Array.isArray(steps)) return [];
  return steps.map((step, index) => ({
    ...step,
    depends_on: Array.isArray(step.depends_on)
      ? step.depends_on.map(item => ({ step_key: item.step_key, outcome: item.outcome }))
      : index === 0
        ? []
        : [{ step_key: steps[index - 1].key, outcome: DEFAULT_OUTCOME }],
  }));
}

export function layoutPipelineGraph(inputSteps) {
  const steps = normalizePipelineSteps(inputSteps);
  const byKey = new Map(steps.map(step => [step.key, step]));
  const layers = new Map();
  const visiting = new Set();

  function getLayer(key) {
    if (layers.has(key)) return layers.get(key);
    if (visiting.has(key)) return 0;
    visiting.add(key);
    const step = byKey.get(key);
    const parents = (step?.depends_on || []).map(item => item.step_key).filter(parent => byKey.has(parent));
    const layer = parents.length ? Math.max(...parents.map(getLayer)) + 1 : 0;
    visiting.delete(key);
    layers.set(key, layer);
    return layer;
  }

  steps.forEach(step => getLayer(step.key));
  const rowsByLayer = new Map();
  steps.forEach(step => {
    const layer = layers.get(step.key) || 0;
    if (!rowsByLayer.has(layer)) rowsByLayer.set(layer, []);
    rowsByLayer.get(layer).push(step);
  });

  const positions = {};
  const orderedLayers = [...rowsByLayer.keys()].sort((a, b) => a - b);
  orderedLayers.forEach(layer => {
    rowsByLayer.get(layer).forEach((step, row) => {
      positions[step.key] = { x: 36 + layer * 270, y: 38 + row * 142, width: 228, height: 104 };
    });
  });
  const maxLayer = Math.max(0, ...orderedLayers);
  const maxRows = Math.max(1, ...[...rowsByLayer.values()].map(rows => rows.length));
  return {
    steps,
    positions,
    width: 36 + (maxLayer + 1) * 270,
    height: 38 + maxRows * 142,
    edges: steps.flatMap(step => (step.depends_on || []).map(dependency => ({
      from: dependency.step_key,
      to: step.key,
      outcome: dependency.outcome,
    })).filter(edge => positions[edge.from] && positions[edge.to])),
  };
}
