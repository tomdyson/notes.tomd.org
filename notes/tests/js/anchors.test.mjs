import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { resolve, contextFor } = require("../../static/notes/anchors.js");

const TEXT =
  "Intro paragraph.\n" +
  "Some text to discuss here.\n" +
  "Another line with some text to discuss again.\n" +
  "The end.";
const QUOTE = "text to discuss here";
const AT = TEXT.indexOf(QUOTE);
const SEL = { quote: QUOTE, prefix: "Some ", suffix: ".\nAnother", offset: AT };

test("empty quote never resolves", () => {
  assert.equal(resolve(TEXT, { quote: "", prefix: "", suffix: "", offset: 0 }), null);
});

test("exact match at the stored offset", () => {
  const r = resolve(TEXT, SEL);
  assert.deepEqual([r.start, r.end, r.method], [AT, AT + QUOTE.length, "exact"]);
});

test("exact match found elsewhere after text was inserted before it", () => {
  const moved = "A new first line.\n" + TEXT;
  const r = resolve(moved, SEL);
  assert.equal(r.method, "exact");
  assert.equal(moved.slice(r.start, r.end), QUOTE);
  assert.equal(r.start, AT + "A new first line.\n".length);
});

test("exact match works without an offset hint", () => {
  const r = resolve(TEXT, { quote: QUOTE, prefix: "", suffix: "", offset: null });
  assert.equal(r.start, AT);
});

test("repeated quote is disambiguated by its context", () => {
  const second = TEXT.indexOf("some text to discuss again") + "some ".length;
  const r = resolve(TEXT, {
    quote: "text to discuss",
    prefix: "line with some ",
    suffix: " again.",
    offset: null,
  });
  assert.equal(r.start, second);
});

test("repeated quote with no context falls back to the nearest to the hint", () => {
  const second = TEXT.indexOf("some text to discuss again") + "some ".length;
  const r = resolve(TEXT, { quote: "text to discuss", prefix: "", suffix: "", offset: second - 3 });
  assert.equal(r.start, second);
});

test("a typo fix inside the quote still resolves, fuzzily", () => {
  const edited = TEXT.replace(QUOTE, "text to discus here");
  const r = resolve(edited, SEL);
  assert.equal(r.method, "fuzzy");
  assert.equal(edited.slice(r.start, r.end), "text to discus here");
});

test("a short insertion inside the quote still resolves", () => {
  const edited = TEXT.replace(QUOTE, "text to now discuss here");
  const r = resolve(edited, SEL);
  assert.equal(r.method, "fuzzy");
  assert.equal(edited.slice(r.start, r.end), "text to now discuss here");
});

test("a substituted edge character keeps the full match", () => {
  const edited = TEXT.replace(QUOTE, "Text to discuss here");
  const r = resolve(edited, SEL);
  assert.equal(edited.slice(r.start, r.end), "Text to discuss here");
});

test("fuzzy matching searches beyond the window around the hint", () => {
  const padding = "filler line that says nothing much at all.\n".repeat(200);
  const far = padding + TEXT.replace(QUOTE, "text to discus here");
  const r = resolve(far, SEL);
  assert.equal(r.method, "fuzzy");
  assert.equal(far.slice(r.start, r.end), "text to discus here");
});

test("a quote that has been deleted is orphaned", () => {
  const edited = TEXT.replace("Intro paragraph.\n", "");
  const r = resolve(edited, { quote: "Intro paragraph", prefix: "", suffix: ".\nSome", offset: 0 });
  assert.equal(r, null);
});

test("a heavily rewritten quote is orphaned rather than mis-anchored", () => {
  const r = resolve(TEXT, { quote: "completely different words", prefix: "", suffix: "", offset: 17 });
  assert.equal(r, null);
});

test("short quotes are never fuzzy-matched", () => {
  assert.equal(resolve("Fin.", { quote: "end", prefix: "The ", suffix: ".", offset: 0 }), null);
});

test("contextFor captures 32 characters either side, clipped at the edges", () => {
  const ctx = contextFor(TEXT, AT, AT + QUOTE.length);
  assert.equal(ctx.prefix, "Intro paragraph.\nSome ");
  assert.equal(ctx.suffix, ".\nAnother line with some text to");
  assert.equal(ctx.prefix.length <= 32 && ctx.suffix.length === 32, true);
  const edge = contextFor(TEXT, 0, 5);
  assert.equal(edge.prefix, "");
});

test("a deleted line is orphaned even when a similar line exists nearby", () => {
  const list = "c. Design class-based architecture\nd. Implement class-based architecture\ne. Add checks";
  const edited = list.replace("c. Design class-based architecture\n", "");
  const r = resolve(edited, {
    quote: "Design class-based architecture",
    prefix: "c. ",
    suffix: "\nd. Implement",
    offset: 3,
  });
  assert.equal(r, null);
});

test("a larger edit still resolves when the surrounding context agrees", () => {
  const list = "c. Design class-based architecture\nd. Implement class-based architecture";
  const edited = list.replace("Design class-based", "Design the class-based");
  const r = resolve(edited, {
    quote: "Design class-based architecture",
    prefix: "c. ",
    suffix: "\nd. Implement",
    offset: 3,
  });
  assert.equal(r.method, "fuzzy");
  assert.equal(edited.slice(r.start, r.end), "Design the class-based architecture");
});

test("a tiny edit resolves even without any stored context", () => {
  const edited = TEXT.replace(QUOTE, "text to discus here");
  const r = resolve(edited, { quote: QUOTE, prefix: "", suffix: "", offset: null });
  assert.equal(edited.slice(r.start, r.end), "text to discus here");
});
