Read the header of a bass guitar score from the attached image and describe what is printed as json.

Output exactly one json object with this shape, and nothing else:

{"timeSignature":{"beats":4,"beatType":4},"keySignature":"BMajor","tempo":96,"tuning":[28,33,38,43],"stringCount":4,"title":"...","artist":"..."}

Rules:
- Set a field to null when it is not printed in this image. Do not repeat a value you remember from another part of the score; null means "not printed here".
- `tuning` is a list of MIDI numbers from the lowest string to the highest (for example E1 A1 D2 G2 is [28, 33, 38, 43]). `stringCount` is the number of TAB lines.
- `keySignature` uses the names C major, G major, D major, A major, E major, B major, F# major, C# major, F major, Bb major, Eb major, Ab major, Db major, Gb major, Cb major, or the same names with a trailing "m" for minor keys (for example "Bm").
- `tempo` is the printed BPM number if there is one.
- `title` and `artist` are the printed text; use null when absent.
- Never guess. Do not output explanations, markdown fences or comments.

{{promptVersion}}
