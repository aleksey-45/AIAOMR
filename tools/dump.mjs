// 把一个 Guitar Pro 文件导成真值 JSON（逐小节的拍号、拍与音符），给 eval/score.py 用。
//   node tools/dump.mjs <file.gp|gp5>   -> 一个 JSON 对象
// alphaTab 的弦号从最低弦数起，正好是本项目的约定，直接透传。
// 真值必须能让 eval/load_truth 校验通过：每小节 beats[].ticks 之和 == 该小节拍号。
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
  // 拍号在 alphaTab 的 MasterBar 上：timeSignatureNumerator / timeSignatureDenominator（1.8.4 实测）。
  const masterBar = bar.masterBar ?? score.masterBars[index];
  const timeSignature = {
    numerator: masterBar.timeSignatureNumerator,
    denominator: masterBar.timeSignatureDenominator,
  };
  const beats = [];
  for (const voice of bar.voices) {
    // alphaTab 读 .gpx 时会给没用到的声部槽位各补一条四分休止（isEmpty === true），
    // 那不是谱面内容；不跳过的话每小节会凭空多出几条休止，真值就不能用。
    if (voice.isEmpty) continue;
    for (const beat of voice.beats) {
      beats.push({
        ticks: beat.playbackDuration,
        duration: beat.duration,     // alphaTab Duration 枚举：1/2/4/8/16/32/64
        dots: beat.dots,
        rest: beat.isRest,
        notes: beat.notes.map((n) => ({
          string: n.string,
          fret: n.fret,
          pitch: n.realValue,
          // 连音：isTieOrigin = 这条是延音的起点，isTieDestination = 这条接上一条延音。
          tie: Boolean(n.isTieOrigin),
          tieFromPrevious: Boolean(n.isTieDestination),
          staccato: Boolean(n.isStaccato),
        })),
      });
    }
  }
  if (beats.length === 0) {
    // GP5 的空小节（整小节休止）一个 beat 都没有；按拍号补一条整小节休止，
    // 时值来自 masterBar.calculateDuration()（拍号算出来的），不是猜的。
    beats.push({ ticks: masterBar.calculateDuration(), duration: 1, dots: 0, rest: true, notes: [] });
  }
  return {
    index: index + 1,
    timeSignature,
    keySignature: masterBar.keySignature,
    beats,
  };
});
console.log(JSON.stringify({
  available: true,
  title: score.title,
  tempo: score.tempo,
  tuning,
  measures,
}));
