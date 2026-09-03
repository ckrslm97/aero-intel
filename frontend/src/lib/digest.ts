/** The model writes markdown; the page rendered it as prose.
 *
 * `tk_service`'s prompt asks for "two short paragraphs plus strong/weak
 * themes" without forbidding markup, and the model reliably answers with
 * `**Genel Bakış**` headings. The BİZ page printed the body into a single
 * `<p>`, so a reader saw the asterisks -- on the one block of the page whose
 * whole job is to be read as sentences.
 *
 * Parsed here rather than fixed only in the prompt, and rather than pulled in
 * as a markdown dependency:
 *
 *   * The prompt cannot repair what is already stored. Digests are kept per
 *     day and the archive would keep its asterisks forever.
 *   * A markdown library would bring a parser, a sanitiser and an HTML sink
 *     for two constructs. This surface has exactly two: a bold run and a
 *     paragraph break. No `dangerouslySetInnerHTML` anywhere.
 *
 * Everything else the model might emit (`#`, `-`, `_`) is deliberately left
 * alone: inventing a renderer for markup we have never actually seen would be
 * guessing at a format instead of reading one.
 */

export interface DigestSpan {
  text: string;
  strong: boolean;
}

const STRONG = /\*\*(.+?)\*\*/g;

/** One paragraph's spans, in order. A `**run**` becomes `strong: true`. */
export function digestSpans(paragraph: string): DigestSpan[] {
  const spans: DigestSpan[] = [];
  let cursor = 0;
  for (const match of paragraph.matchAll(STRONG)) {
    const start = match.index ?? 0;
    if (start > cursor) spans.push({ text: paragraph.slice(cursor, start), strong: false });
    spans.push({ text: match[1], strong: true });
    cursor = start + match[0].length;
  }
  if (cursor < paragraph.length) spans.push({ text: paragraph.slice(cursor), strong: false });
  return spans;
}

/** The body split into paragraphs, blank runs dropped.
 *
 * Blank lines separate sections, but a heading is just as often followed by a
 * SINGLE newline -- so a line that is nothing but a `**...**` run is its own
 * paragraph either way, and the heading never runs into the sentence beneath
 * it. That is the whole rule; everything else joins the paragraph it is in.
 */
export function digestParagraphs(body: string): string[] {
  const paragraphs: string[] = []
  let current: string[] = []

  const flush = () => {
    const joined = current.join(" ").trim()
    if (joined) paragraphs.push(joined)
    current = []
  }

  for (const rawLine of body.split("\n")) {
    const line = rawLine.trim()
    if (!line) {
      flush()
      continue
    }
    if (HEADING_LINE.test(line)) {
      flush()
      paragraphs.push(line)
      continue
    }
    current.push(line)
  }
  flush()
  return paragraphs
}

/** A line that is entirely one bold run: the model's section heading. */
const HEADING_LINE = /^\*\*[^*]+\*\*$/
