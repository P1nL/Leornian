export function normalizeParameter(value, min, max, step = 1) {
  const bounded = Math.min(max, Math.max(min, value));
  return Number(Math.min(max, Math.max(min, min + Math.round((bounded - min) / step) * step)).toFixed(10));
}

export function lineDiff(before, after) {
  const split = (text) => text === '' ? [] : text.replaceAll('\r\n', '\n').split('\n');
  const oldLines = split(before);
  const newLines = split(after);
  let start = 0;
  while (start < oldLines.length && start < newLines.length && oldLines[start] === newLines[start]) start++;
  let end = 0;
  while (end < oldLines.length - start && end < newLines.length - start
    && oldLines[oldLines.length - 1 - end] === newLines[newLines.length - 1 - end]) end++;
  const oldMiddle = oldLines.slice(start, oldLines.length - end);
  const newMiddle = newLines.slice(start, newLines.length - end);
  const edits = oldLines.slice(0, start).map((text) => ({ kind: 'same', text }));
  const append = (kind, text) => edits.push({ kind, text });
  // Large edits keep an exact, non-minimal diff rather than blocking the editor with a quadratic table.
  if (oldMiddle.length * newMiddle.length > 1_000_000) {
    oldMiddle.forEach((text) => append('removed', text));
    newMiddle.forEach((text) => append('added', text));
  } else {
    const lengths = Array.from({ length: oldMiddle.length + 1 }, () => new Uint32Array(newMiddle.length + 1));
    for (let i = oldMiddle.length - 1; i >= 0; i--) {
      for (let j = newMiddle.length - 1; j >= 0; j--) {
        lengths[i][j] = oldMiddle[i] === newMiddle[j] ? lengths[i + 1][j + 1] + 1
          : Math.max(lengths[i + 1][j], lengths[i][j + 1]);
      }
    }
    let i = 0;
    let j = 0;
    while (i < oldMiddle.length || j < newMiddle.length) {
      if (i < oldMiddle.length && j < newMiddle.length && oldMiddle[i] === newMiddle[j]) {
        append('same', oldMiddle[i++]); j++;
      } else if (i < oldMiddle.length && (j === newMiddle.length || lengths[i + 1][j] >= lengths[i][j + 1])) {
        append('removed', oldMiddle[i++]);
      } else append('added', newMiddle[j++]);
    }
  }
  oldLines.slice(oldLines.length - end).forEach((text) => append('same', text));
  let oldLine = 0;
  let newLine = 0;
  return edits.map((entry) => ({
    ...entry, beforeLine: entry.kind === 'added' ? null : ++oldLine,
    afterLine: entry.kind === 'removed' ? null : ++newLine,
  }));
}

export function inlineDiffModel(before, after) {
  const lines = [];
  const deletions = [];
  let pending = [];
  for (const row of lineDiff(before, after)) {
    if (row.kind === 'removed') { pending.push(row); continue; }
    if (pending.length) { deletions.push({ atLine: row.afterLine, rows: pending }); pending = []; }
    lines.push(row);
  }
  if (pending.length) deletions.push({ atLine: null, rows: pending });
  return { lines, deletions };
}
