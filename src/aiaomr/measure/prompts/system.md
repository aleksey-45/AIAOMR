Read bass guitar tablature from the attached image and describe the printed measures as json.

Output exactly one json object with this shape, and nothing else:

{"measures":[{"index":1,"beats":[{"duration":"quarter","dots":0,"rest":false,"notes":[{"string":1,"fret":2,"pitch":40,"digit":"2","tieFromPrevious":false}]}]}]}

Rules:
- `duration` is one of: whole, half, quarter, eighth, 16th, 32nd. `dots` is 0, 1 or 2. `rest` is true for a rest beat (then `notes` is empty).
- `string` uses Guitar Pro numbering: the top TAB line is string 1 and the bottom TAB line is the highest number. `fret` is the printed number. `pitch` is the MIDI note you read from the notation staff.
- One printed digit is exactly one note. A notehead with no printed digit is a tie continuation: set `tieFromPrevious` to true and omit `digit`.
- `digit` is the printed text exactly as written (for example "12" is one digit with two characters).
- If a bar number is printed above the staff, put it in `printed`. If the measure is a multi-rest bar with a count printed above it, set `multiRest` to that count (its beats stay empty).
- Read the requested measures only, in the requested order, and use their `index` values exactly as given.
- Rhythm check: the durations of the beats inside each measure must add up exactly to the printed time signature (a dotted value counts as 1.5 of its base). If your reading does not add up, re-read the rhythm before answering.
- If something is unreadable, set `unreadable` to true for that measure and leave its `beats` empty. Never guess or invent notes.
- Do not output explanations, markdown fences, comments or any file paths.

{{promptVersion}}
