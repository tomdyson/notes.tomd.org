/* Text-quote anchoring: re-find a passage a reader selected in a note whose
 * text may have changed since. Follows the W3C Web Annotation model — the
 * quote itself, a few characters of prefix/suffix context, and a start offset
 * used only as a hint. Pure string functions with no DOM access, so the
 * resolve cascade is unit-tested under node (notes/tests/js/).
 *
 * Cascade: exact at the hinted offset → exact anywhere (context picks between
 * repeats) → approximate match within a small error budget → null (orphan).
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.NoteAnchors = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var CONTEXT_CHARS = 32;
  var MAX_ERROR_RATE = 0.25; // fraction of the quote's length that may differ
  var FUZZY_WINDOW = 2000;   // chars either side of the hint to search first
  var SMALL_EDIT = 2;        // errors accepted without any context agreement
  var MIN_CONTEXT = 4;       // context chars that must agree for larger edits

  function contextFor(text, start, end) {
    return {
      prefix: text.slice(Math.max(0, start - CONTEXT_CHARS), start),
      suffix: text.slice(end, end + CONTEXT_CHARS),
    };
  }

  function findAll(text, quote) {
    var out = [];
    var i = text.indexOf(quote);
    while (i !== -1) {
      out.push(i);
      i = text.indexOf(quote, i + 1);
    }
    return out;
  }

  function commonSuffix(a, b) {
    var n = 0;
    while (n < a.length && n < b.length && a[a.length - 1 - n] === b[b.length - 1 - n]) n++;
    return n;
  }

  function commonPrefix(a, b) {
    var n = 0;
    while (n < a.length && n < b.length && a[n] === b[n]) n++;
    return n;
  }

  // How many characters of stored prefix/suffix agree with the text around
  // a candidate span.
  function contextAgreement(text, start, end, sel) {
    var before = text.slice(Math.max(0, start - CONTEXT_CHARS), start);
    var after = text.slice(end, end + CONTEXT_CHARS);
    return commonSuffix(before, sel.prefix || "") + commonPrefix(after, sel.suffix || "");
  }

  // Among several exact occurrences, prefer the one whose surroundings agree
  // most with the stored context; ties go to the occurrence nearest the hint.
  function pickByContext(text, candidates, sel) {
    var best = null;
    candidates.forEach(function (start) {
      var end = start + sel.quote.length;
      var score = contextAgreement(text, start, end, sel);
      var dist = sel.offset == null ? 0 : Math.abs(start - sel.offset);
      if (!best || score > best.score || (score === best.score && dist < best.dist)) {
        best = { start: start, score: score, dist: dist };
      }
    });
    return best.start;
  }

  // Sellers' algorithm: for every end position in text, the edit distance to
  // the closest substring ending there. Returns the end with the fewest
  // errors (ties: nearest to hint), or null when nothing is within budget.
  function bestEnd(text, pattern, maxErrors, hint) {
    var m = pattern.length;
    var n = text.length;
    var prev = new Int32Array(m + 1);
    var cur = new Int32Array(m + 1);
    var swap;
    var i;
    for (i = 0; i <= m; i++) prev[i] = i;
    var best = null;
    for (var j = 1; j <= n; j++) {
      cur[0] = 0;
      var tc = text.charCodeAt(j - 1);
      for (i = 1; i <= m; i++) {
        var sub = prev[i - 1] + (pattern.charCodeAt(i - 1) === tc ? 0 : 1);
        var del = prev[i] + 1;
        var ins = cur[i - 1] + 1;
        cur[i] = sub < del ? (sub < ins ? sub : ins) : (del < ins ? del : ins);
      }
      var errors = cur[m];
      if (errors <= maxErrors) {
        var dist = hint == null ? 0 : Math.abs(j - m - hint);
        if (!best || errors < best.errors || (errors === best.errors && dist < best.dist)) {
          best = { end: j, errors: errors, dist: dist };
        }
      }
      swap = prev; prev = cur; cur = swap;
    }
    return best;
  }

  function reverse(s) {
    return s.split("").reverse().join("");
  }

  function approxSearch(text, pattern, maxErrors, hint) {
    var fwd = bestEnd(text, pattern, maxErrors, hint);
    if (!fwd) return null;
    // Run the same search backwards from the end we found to locate the start.
    // A hint of 0 makes ties prefer a match as long as the pattern.
    var windowStart = Math.max(0, fwd.end - pattern.length - maxErrors);
    var back = bestEnd(reverse(text.slice(windowStart, fwd.end)), reverse(pattern), fwd.errors, 0);
    return { start: fwd.end - back.end, end: fwd.end, errors: fwd.errors };
  }

  function fuzzyResolve(text, quote, hint, maxErrors) {
    if (hint != null && text.length > FUZZY_WINDOW * 2) {
      var lo = Math.max(0, hint - FUZZY_WINDOW);
      var hi = Math.min(text.length, hint + quote.length + FUZZY_WINDOW);
      var local = approxSearch(text.slice(lo, hi), quote, maxErrors, hint - lo);
      if (local) return { start: local.start + lo, end: local.end + lo, errors: local.errors };
    }
    return approxSearch(text, quote, maxErrors, hint);
  }

  function resolve(text, sel) {
    var quote = sel.quote || "";
    if (!quote || !text) return null;
    var hint = Number.isInteger(sel.offset) ? sel.offset : null;

    if (hint !== null && text.startsWith(quote, hint)) {
      return { start: hint, end: hint + quote.length, method: "exact" };
    }
    var hits = findAll(text, quote);
    if (hits.length) {
      var start = hits.length === 1
        ? hits[0]
        : pickByContext(text, hits, { quote: quote, prefix: sel.prefix, suffix: sel.suffix, offset: hint });
      return { start: start, end: start + quote.length, method: "exact" };
    }
    var maxErrors = Math.floor(quote.length * MAX_ERROR_RATE);
    if (maxErrors > 0) {
      var fz = fuzzyResolve(text, quote, hint, maxErrors);
      // A typo-sized edit is trusted on its own. Anything bigger must be
      // corroborated by the surrounding text, or a deleted passage would be
      // pinned to whatever similar phrase remains nearby.
      if (fz && (fz.errors <= SMALL_EDIT || contextAgreement(text, fz.start, fz.end, sel) >= MIN_CONTEXT)) {
        return { start: fz.start, end: fz.end, method: "fuzzy", errors: fz.errors };
      }
    }
    return null;
  }

  return {
    resolve: resolve,
    contextFor: contextFor,
    findAll: findAll,
    pickByContext: pickByContext,
    approxSearch: approxSearch,
    CONTEXT_CHARS: CONTEXT_CHARS,
  };
});
