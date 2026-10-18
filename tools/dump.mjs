// 把一个 Guitar Pro 文件导成真值 JSON（逐小节的拍与音符），给 eval/score.py 用。
//   node tools/dump.mjs <file.gp|gp5>   -> 一个 JSON 对象
// alphaTab 的弦号从最低弦数起，正好是本项目的约定，直接透传。
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';

async function loadAlphaTab() {
  const candidates = [];
  if (process.env.ALPHATAB_PATH) candidates.push(pathToFileURL(process.env.ALPHATAB_PATH).href);
  candidates.push(new URL('./alphatab/dist/alphaTab.core.mjs', import.meta.url).href);
  for (const url of candidates) {
    try {
      return await import(url);
    } catch {
      // 继续试
    }
  }
  return null;
}

const at = await loadAlphaTab();
if (at === null) {
  console.log(JSON.stringify({ available: false }));
  process.exit(2);
}
const file = process.argv[2];
if (!file) {
  console.log(JSON.stringify({ available: false, error: 'usage: node tools/dump.mjs <file>' }));
  process.exit(2);
}
const score = at.importer.ScoreLoader.loadScoreFromBytes(new Uint8Array(fs.readFileSync(file)));
const staff = score.tracks[0].staves[0];
const tuning = [...(staff.stringTuning?.tunings ?? [])].reverse();
const measures = staff.bars.map((bar, index) => {
  const beats = [];
  for (const voice of bar.voices) {
    for (const beat of voice.beats) {
      beats.push({
        ticks: beat.playbackDuration,
        rest: beat.isRest,
        notes: beat.notes.map((n) => ({ string: n.string, fret: n.fret, pitch: n.realValue })),
      });
    }
  }
  return { index: index + 1, beats };
});
console.log(JSON.stringify({ available: true, title: score.title, tuning, measures }));
