// 用 alphaTab 独立审计 gp5：音高恒等式（音高 == 空弦 + 品位）与小节时值（拍数之和 == 拍号）。
//
// 用法：
//   node tools/audit.mjs <file.gp5>
// alphaTab 从 ALPHATAB_PATH 指向的模块文件加载；也可以在本目录 `npm i @coderline/alphatab`
// 让它走默认解析。找不到 alphaTab 时输出 {"available": false} 并以 2 退出。
//
// 输出一个 JSON 对象（stdout）：
//   {"available":true,"files":1,"notes":N,"pitchMismatch":0,"barErrors":0,"details":[...]}

import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const N = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const mn = (m) => N[((m % 12) + 12) % 12] + (Math.floor(m / 12) - 1);
const QT = 960;

async function loadAlphaTab() {
  const candidates = [];
  if (process.env.ALPHATAB_PATH) candidates.push(pathToFileURL(process.env.ALPHATAB_PATH).href);
  candidates.push(new URL('./alphatab/dist/alphaTab.core.mjs', import.meta.url).href);
  for (const url of candidates) {
    try {
      const at = await import(url);
      return at;
    } catch {
      // 继续试下一个
    }
  }
  return null;
}

function fail(message, code = 2) {
  console.log(JSON.stringify({ available: false, error: message }));
  process.exit(code);
}

const at = await loadAlphaTab();
if (at === null) {
  fail('alphaTab not found; set ALPHATAB_PATH or run npm i @coderline/alphatab in tools/');
}

const files = process.argv.slice(2);
if (files.length === 0) {
  fail('usage: node tools/audit.mjs <file.gp5>');
}

const details = [];
let notes = 0;
let pitchMismatch = 0;
let barErrors = 0;

for (const file of files) {
  const bytes = new Uint8Array(fs.readFileSync(file));
  let score;
  try {
    score = at.importer.ScoreLoader.loadScoreFromBytes(bytes);
  } catch (error) {
    fail(`parse failed for ${path.basename(file)}: ${error.message}`, 2);
  }
  for (const track of score.tracks) {
    for (let si = 0; si < track.staves.length; si++) {
      const staff = track.staves[si];
      const tuning = staff.stringTuning?.tunings ?? [];
      if (!tuning.length) continue;
      const T = tuning.length;
      for (const bar of staff.bars) {
        const master = bar.masterBar;
        const expected = master.timeSignatureNumerator * ((4 * QT) / master.timeSignatureDenominator);
        for (let vi = 0; vi < bar.voices.length; vi++) {
          const voice = bar.voices[vi];
          let span = 0;
          let realNotes = 0;
          for (const beat of voice.beats) {
            span += beat.playbackDuration;
            if (beat.isRest) continue;
            realNotes += beat.notes.length;
            for (const note of beat.notes) {
              notes += 1;
              const expectedPitch = tuning[T - note.string] + note.fret;
              if (expectedPitch !== note.realValue) {
                pitchMismatch += 1;
                details.push(
                  `pitch bar ${bar.index + 1}: string=${note.string} fret=${note.fret} ` +
                    `sounded=${mn(note.realValue)} expected=${mn(expectedPitch)}`
                );
              }
            }
          }
          if (realNotes > 0 && Math.abs(span - expected) > 1) {
            barErrors += 1;
            details.push(
              `bar ${bar.index + 1} voice${vi}: ${realNotes} notes span ${span} ticks, ` +
                `${master.timeSignatureNumerator}/${master.timeSignatureDenominator} needs ${expected}`
            );
          }
        }
      }
    }
  }
}

console.log(
  JSON.stringify({
    available: true,
    files: files.length,
    notes,
    pitchMismatch,
    barErrors,
    details: details.slice(0, 50),
  })
);
