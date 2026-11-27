// Compact only the standard-cell rectangles emitted by task_artifacts.render.
// Hard macro names, coordinates, legend and scale stay available in the view.
const cellRow = /^<g><title>[^<]*<\/title><rect x="(-?[\d.]+)" y="(-?[\d.]+)" width="([\d.]+)" height="([\d.]+)" fill="#347db7" stroke="#ffffff" stroke-width="0\.12"\/><\/g>$/;

export function placementView(data) {
  if (data.length < 2 * 1024 * 1024) return data;
  const lines = data.toString('utf8').split('\n');
  const output = [];
  const paths = [];
  function flush() {
    if (!paths.length) return;
    output.push(`<path data-cell-count="${paths.length}" fill="#347db7" stroke="#ffffff" stroke-width="0.12" d="${paths.join('')}"/>`);
    paths.length = 0;
  }
  for (const line of lines) {
    const cell = cellRow.exec(line);
    if (cell) {
      const [, x, y, width, height] = cell;
      paths.push(`M${x} ${y}h${width}v${height}h-${width}Z`);
      if (paths.length === 256) flush();
    } else {
      flush();
      output.push(line);
    }
  }
  flush();
  return Buffer.from(output.join('\n'));
}
