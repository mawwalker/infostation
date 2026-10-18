// Render driver called by the Python pipeline: bundle once, then render every job in a job file.
// Usage: node render.mjs <job.json>
// job.json = {publicDir, concurrency, jobs: [{kind: "video"|"still", composition, props, out}]}
import {bundle} from '@remotion/bundler';
import {renderMedia, renderStill, selectComposition} from '@remotion/renderer';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const job = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));

const serveUrl = await bundle({
  entryPoint: path.join(here, 'src/index.ts'),
  publicDir: job.publicDir,
  onProgress: () => undefined,
});

for (const j of job.jobs) {
  const t0 = Date.now();
  const composition = await selectComposition({serveUrl, id: j.composition, inputProps: j.props});
  fs.mkdirSync(path.dirname(j.out), {recursive: true});
  if (j.kind === 'video') {
    let last = -1;
    await renderMedia({
      serveUrl, composition, inputProps: j.props, codec: 'h264', outputLocation: j.out,
      concurrency: job.concurrency ?? null, crf: 20, pixelFormat: 'yuv420p', audioBitrate: '192k',
      onProgress: ({progress}) => {
        const pct = Math.floor(progress * 100);
        if (pct % 10 === 0 && pct !== last) {
          last = pct;
          console.log(`[render] ${path.basename(j.out)} ${pct}%`);
        }
      },
    });
  } else {
    await renderStill({serveUrl, composition, inputProps: j.props, output: j.out, imageFormat: 'png'});
  }
  console.log(`[render] done ${j.out} in ${((Date.now() - t0) / 1000).toFixed(1)}s`);
}
