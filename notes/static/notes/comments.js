/* Anchored comments on the note page.
 *
 *  - Selecting text in the note shows a "Comment" button; choosing it fills
 *    the hidden selector fields of the new-comment form and shows a chip.
 *  - On load, every anchored comment is re-found in the rendered text via
 *    NoteAnchors and wrapped in <mark> elements; ones that no longer resolve
 *    are marked orphaned and get their "text has changed" badge shown.
 *  - Highlights and thread items link both ways (click to jump, hover to pair).
 *
 * Offsets are measured over the concatenated text nodes of .note-body,
 * skipping Mermaid diagrams (replaced by SVG at runtime), so the same text is
 * used when capturing a selection and when resolving it later.
 */
(function () {
  "use strict";

  var body = document.querySelector(".note-body");
  var section = document.getElementById("comments");
  var Anchors = window.NoteAnchors;
  if (!body || !section || !Anchors) return;

  var MAX_QUOTE = 2000; // matches the server-side cap
  var CHIP_CHARS = 120;
  var replyDismissArmed = false;

  // ---- text <-> DOM mapping ------------------------------------------------

  function isExcluded(node) {
    for (var el = node.parentElement; el && el !== body; el = el.parentElement) {
      if (el.classList.contains("mermaid")) return true;
    }
    return false;
  }

  function segments() {
    var walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        return isExcluded(node) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
      },
    });
    var segs = [];
    var pos = 0;
    var node;
    while ((node = walker.nextNode())) {
      segs.push({ node: node, start: pos, end: pos + node.data.length });
      pos += node.data.length;
    }
    return segs;
  }

  function textOf(segs) {
    return segs.map(function (s) { return s.node.data; }).join("");
  }

  // Global offsets of the part of a Range that lies inside the note, or null
  // if none of it does. A selection that runs past the note (a triple-click
  // on the last paragraph often does) is clamped to the note's text.
  function rangeToOffsets(range, segs) {
    var first = -1;
    var last = -1;
    for (var i = 0; i < segs.length; i++) {
      if (range.intersectsNode(segs[i].node)) {
        if (first === -1) first = i;
        last = i;
      }
    }
    if (first === -1) return null;
    var s = segs[first];
    var e = segs[last];
    return {
      start: range.startContainer === s.node ? s.start + range.startOffset : s.start,
      end: range.endContainer === e.node ? e.start + range.endOffset : e.end,
    };
  }

  function trimOffsets(text, off) {
    var start = off.start;
    var end = off.end;
    while (start < end && /\s/.test(text[start])) start++;
    while (end > start && /\s/.test(text[end - 1])) end--;
    return start < end ? { start: start, end: end } : null;
  }

  // Wrap the text between two global offsets in <mark>s, one per text node.
  function highlight(start, end, id, extraClass) {
    var marks = [];
    segments().forEach(function (seg) {
      if (seg.end <= start || seg.start >= end) return;
      var from = Math.max(start, seg.start) - seg.start;
      var to = Math.min(end, seg.end) - seg.start;
      if (to <= from || !seg.node.data.slice(from, to).trim()) return;
      var node = seg.node;
      if (to < node.data.length) node.splitText(to);
      if (from > 0) node = node.splitText(from);
      var mark = document.createElement("mark");
      mark.className = "comment-highlight" + (extraClass ? " " + extraClass : "");
      mark.dataset.commentId = id;
      node.parentNode.insertBefore(mark, node);
      mark.appendChild(node);
      marks.push(mark);
    });
    return marks;
  }

  function unwrap(marks) {
    marks.forEach(function (mark) {
      var parent = mark.parentNode;
      if (!parent) return;
      while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
      parent.removeChild(mark);
      parent.normalize();
    });
  }

  function marksFor(id) {
    return Array.prototype.slice.call(
      body.querySelectorAll('mark.comment-highlight[data-comment-id="' + id + '"]')
    );
  }

  // ---- pairing highlights with thread items ---------------------------------

  function setActive(id, on) {
    marksFor(id).forEach(function (m) { m.classList.toggle("is-active", on); });
    var li = document.getElementById("comment-" + id);
    if (li) li.classList.toggle("is-active", on);
  }

  var flashTimers = {};
  function flash(id) {
    setActive(id, true);
    clearTimeout(flashTimers[id]);
    flashTimers[id] = setTimeout(function () { setActive(id, false); }, 1600);
  }

  function pair(el, id) {
    el.addEventListener("mouseenter", function () { setActive(id, true); });
    el.addEventListener("mouseleave", function () { setActive(id, false); });
  }

  function jumpTo(el, id) {
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    flash(id);
  }

  // ---- resolve stored anchors ----------------------------------------------

  function resolveAll() {
    var text = textOf(segments());
    var resolved = [];
    section.querySelectorAll("li[data-quote]").forEach(function (li) {
      var offset = parseInt(li.dataset.offset, 10);
      var hit = Anchors.resolve(text, {
        quote: li.dataset.quote,
        prefix: li.dataset.prefix,
        suffix: li.dataset.suffix,
        offset: isNaN(offset) ? null : offset,
      });
      if (hit) {
        li.classList.add("is-anchored");
        resolved.push({ li: li, hit: hit });
      } else {
        li.classList.add("is-orphaned");
        var badge = li.querySelector("[data-orphan-badge]");
        if (badge) badge.hidden = false;
      }
    });
    resolved.forEach(function (r) {
      var id = r.li.dataset.commentId;
      highlight(r.hit.start, r.hit.end, id).forEach(function (mark) {
        pair(mark, id);
        mark.addEventListener("click", function () { jumpTo(r.li, id); });
      });
      pair(r.li, id);
      var quote = r.li.querySelector("[data-comment-quote]");
      if (quote) {
        quote.addEventListener("click", function () {
          var marks = marksFor(id);
          if (marks.length) jumpTo(marks[0], id);
        });
      }
    });
  }

  // On desktop, place anchored threads beside their text. Comments that are
  // close together are pushed down just enough to avoid overlapping.
  var threadList = null;
  var layoutFrame = null;
  var threadObserver = null;
  var watchingThreadResize = false;

  function resetThreadLayout() {
    if (!threadList) return;
    threadList.classList.remove("is-positioned");
    threadList.style.height = "";
    threadList.querySelectorAll(":scope > li.comment-thread").forEach(function (thread) {
      thread.style.top = "";
    });
  }

  function alignThreads() {
    layoutFrame = null;
    if (!threadList) return;
    if (!window.matchMedia("(min-width: 1200px)").matches) {
      resetThreadLayout();
      return;
    }

    var threads = Array.prototype.slice.call(
      threadList.querySelectorAll(":scope > li.comment-thread")
    );
    if (!threads.length) return;

    threadList.classList.add("is-positioned");
    var listTop = threadList.getBoundingClientRect().top;
    var items = threads.map(function (thread, index) {
      var marks = marksFor(thread.dataset.commentId);
      return {
        thread: thread,
        index: index,
        anchored: marks.length > 0,
        target: marks.length
          ? Math.max(0, marks[0].getBoundingClientRect().top - listTop)
          : 0,
      };
    });

    items.sort(function (a, b) {
      if (a.anchored !== b.anchored) return a.anchored ? 1 : -1;
      return a.target - b.target || a.index - b.index;
    });

    var gap = parseFloat(window.getComputedStyle(document.documentElement).fontSize) * 0.5;
    var cursor = 0;
    items.forEach(function (item) {
      var top = Math.max(cursor, item.target);
      item.thread.style.top = top + "px";
      cursor = top + item.thread.offsetHeight + gap;
    });
    threadList.style.height = Math.max(0, cursor - gap) + "px";
  }

  function scheduleThreadLayout() {
    if (layoutFrame !== null) window.cancelAnimationFrame(layoutFrame);
    layoutFrame = window.requestAnimationFrame(alignThreads);
  }

  function positionFloatingComposer() {
    var composer = section && section.querySelector("[data-comment-composer].is-floating");
    if (!composer) return;
    var rail = section.getBoundingClientRect();
    var selected = pendingMarks.length ? pendingMarks[0].getBoundingClientRect() : null;
    var desiredTop = selected ? selected.top : 16;
    var maxTop = Math.max(16, window.innerHeight - composer.offsetHeight - 16);
    composer.style.left = rail.left + "px";
    composer.style.width = rail.width + "px";
    composer.style.top = Math.max(16, Math.min(desiredTop, maxTop)) + "px";
  }

  function watchThreadLayout() {
    if (!threadList) return;
    if (!watchingThreadResize) {
      window.addEventListener("resize", function () {
        scheduleThreadLayout();
        positionFloatingComposer();
      });
      watchingThreadResize = true;
    }
    if (threadObserver) threadObserver.disconnect();
    if (window.ResizeObserver) {
      threadObserver = new ResizeObserver(function () {
        scheduleThreadLayout();
        positionFloatingComposer();
      });
      threadObserver.observe(body);
      var composer = section.querySelector("[data-comment-composer]");
      if (composer) threadObserver.observe(composer);
      threadList.querySelectorAll(":scope > li.comment-thread").forEach(function (thread) {
        threadObserver.observe(thread);
      });
    }
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(scheduleThreadLayout);
    }
  }

  // ---- the new-comment form ------------------------------------------------

  var form = null;
  var chip = null;
  var chipText = null;
  var pendingMarks = [];

  function field(name) {
    return form.querySelector('input[type="hidden"][name="' + name + '"]');
  }

  function showChip(quote) {
    chipText.textContent = quote.length > CHIP_CHARS ? quote.slice(0, CHIP_CHARS - 1) + "…" : quote;
    chip.hidden = false;
  }

  function setAnchor(sel) {
    field("quote").value = sel.quote;
    field("prefix").value = sel.prefix;
    field("suffix").value = sel.suffix;
    field("start_offset").value = sel.start;
    showChip(sel.quote);
    unwrap(pendingMarks);
    pendingMarks = highlight(sel.start, sel.end, "pending", "is-pending");
    var composer = form.closest("[data-comment-composer]");
    if (composer) composer.open = true;
    if (window.matchMedia("(min-width: 1200px)").matches) {
      composer.classList.add("is-floating");
      positionFloatingComposer();
    } else {
      form.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    var textarea = form.querySelector("textarea");
    if (textarea) textarea.focus({ preventScroll: true });
  }

  function clearAnchor() {
    ["quote", "prefix", "suffix", "start_offset"].forEach(function (name) { field(name).value = ""; });
    chip.hidden = true;
    unwrap(pendingMarks);
    pendingMarks = [];
    var composer = form.closest("[data-comment-composer]");
    if (composer) {
      composer.classList.remove("is-floating");
      composer.style.left = "";
      composer.style.top = "";
      composer.style.width = "";
    }
  }

  // ---- selection popover ---------------------------------------------------

  var popover = document.createElement("button");
  popover.type = "button";
  popover.className = "comment-popover";
  popover.textContent = "Comment";
  popover.hidden = true;
  document.body.appendChild(popover);

  var pending = null;
  var mouseDown = false;
  var timer = null;

  function currentSelection() {
    var sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
    var range = sel.getRangeAt(0);
    var segs = segments();
    var off = rangeToOffsets(range, segs);
    if (!off) return null;
    var text = textOf(segs);
    off = trimOffsets(text, off);
    if (!off || off.end - off.start > MAX_QUOTE) return null;
    var ctx = Anchors.contextFor(text, off.start, off.end);
    return {
      start: off.start,
      end: off.end,
      quote: text.slice(off.start, off.end),
      prefix: ctx.prefix,
      suffix: ctx.suffix,
      rect: anchorRect(range),
    };
  }

  // The last line box of the selection that lies inside the note, so the
  // button sits by the end of what was selected rather than over a bounding
  // box that a triple-click stretches into the next block.
  function anchorRect(range) {
    var limit = body.getBoundingClientRect().bottom - 1;
    var rects = Array.prototype.filter.call(range.getClientRects(), function (r) {
      return r.width > 0 && r.height > 0 && r.top < limit;
    });
    return rects.length ? rects[rects.length - 1] : range.getBoundingClientRect();
  }

  function showPopover(sel) {
    popover.hidden = false;
    var r = sel.rect;
    var width = popover.offsetWidth;
    var height = popover.offsetHeight;
    var top = window.scrollY + r.top + (r.height - height) / 2;
    var minTop = window.scrollY + 8;
    var maxTop = window.scrollY + document.documentElement.clientHeight - height - 8;
    top = Math.max(minTop, Math.min(top, maxTop));
    var left = window.scrollX + r.right + 4;
    var maxLeft = window.scrollX + document.documentElement.clientWidth - width - 8;
    left = Math.max(window.scrollX + 8, Math.min(left, maxLeft));
    popover.style.top = top + "px";
    popover.style.left = left + "px";
  }

  function hidePopover() {
    popover.hidden = true;
    pending = null;
  }

  function checkSelection() {
    if (mouseDown) return;
    var sel = currentSelection();
    if (!sel) { hidePopover(); return; }
    pending = sel;
    showPopover(sel);
  }

  document.addEventListener("selectionchange", function () {
    clearTimeout(timer);
    timer = setTimeout(checkSelection, 150);
  });
  document.addEventListener("mousedown", function (e) {
    if (e.target === popover) return;
    mouseDown = true;
  });
  document.addEventListener("mouseup", function () {
    mouseDown = false;
    clearTimeout(timer);
    timer = setTimeout(checkSelection, 0);
  });
  window.addEventListener("scroll", function () {
    if (pending) showPopover(pending);
    positionFloatingComposer();
  }, { passive: true });

  popover.addEventListener("mousedown", function (e) { e.preventDefault(); });
  popover.addEventListener("click", function () {
    if (!pending || !form) return;
    var sel = pending;
    hidePopover();
    window.getSelection().removeAllRanges();
    setAnchor(sel);
  });

  // ---- deleting: inline two-step instead of a native confirm() ------------

  function armDeleteForms() {
    section.querySelectorAll("form[data-confirm-delete]").forEach(function (form) {
      form.removeAttribute("onsubmit");
      var button = form.querySelector("button");
      var label = button.textContent;
      var cancel = document.createElement("button");
      cancel.type = "button";
      cancel.textContent = "cancel";
      cancel.className = "hover:text-stone-800";
      cancel.hidden = true;
      form.appendChild(cancel);
      var timer = null;

      function disarm() {
        clearTimeout(timer);
        form.dataset.armed = "";
        button.textContent = label;
        button.classList.remove("text-rose-700", "font-medium");
        cancel.hidden = true;
      }

      button.addEventListener("click", function (e) {
        if (form.dataset.armed) return; // second click submits normally
        e.preventDefault();
        form.dataset.armed = "1";
        button.textContent = "confirm delete";
        button.classList.add("text-rose-700", "font-medium");
        cancel.hidden = false;
        timer = setTimeout(disarm, 6000);
      });
      cancel.addEventListener("click", disarm);
    });
  }

  // Clicking a thread card opens its reply form without reserving a visible
  // action row. Interactive children keep their own click behaviour.
  function armReplyCards() {
    var threads = section.querySelectorAll("li.comment-thread");

    function openReply(thread) {
      threads.forEach(function (other) {
        var otherDetails = other.querySelector(":scope > [data-reply-control]");
        if (otherDetails && other !== thread) otherDetails.open = false;
      });
      var details = thread.querySelector(":scope > [data-reply-control]");
      if (details) details.open = true;
    }

    threads.forEach(function (thread) {
      thread.addEventListener("click", function (event) {
        if (event.target.closest("a, button, form, input, textarea, select, label, details")) return;
        var selection = window.getSelection();
        if (selection && !selection.isCollapsed) return;
        openReply(thread);
      });
      thread.addEventListener("keydown", function (event) {
        if (event.target !== thread || (event.key !== "Enter" && event.key !== " ")) return;
        event.preventDefault();
        openReply(thread);
        var textarea = thread.querySelector(":scope > [data-reply-control] textarea");
        if (textarea) textarea.focus();
      });
    });

    if (!replyDismissArmed) {
      document.addEventListener("click", function (event) {
        var openReply = section && section.querySelector("[data-reply-control][open]");
        if (!openReply) return;
        var thread = openReply.closest("li.comment-thread");
        if (thread && !thread.contains(event.target)) openReply.open = false;
      });
      document.addEventListener("keydown", function (event) {
        if (event.key !== "Escape" || !section) return;
        var openReplies = section.querySelectorAll("[data-reply-control][open]");
        if (!openReplies.length) return;
        event.preventDefault();
        var thread = openReplies[0].closest("li.comment-thread");
        openReplies.forEach(function (details) { details.open = false; });
        if (thread) thread.focus({ preventScroll: true });
      });
      replyDismissArmed = true;
    }
  }

  function armEnterToSubmit() {
    section.querySelectorAll('form textarea[name="body"]').forEach(function (textarea) {
      textarea.addEventListener("keydown", function (event) {
        if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
        event.preventDefault();
        textarea.form.requestSubmit();
      });
    });
  }

  function armCommentComposer() {
    var composer = section.querySelector("[data-comment-composer]");
    if (!composer) return;

    function syncComposerState() {
      section.classList.toggle("is-adding-comment", composer.open);
      if (!composer.open && composer.classList.contains("is-floating")) clearAnchor();
    }

    composer.addEventListener("toggle", syncComposerState);
    syncComposerState();
  }

  function preserveCommentScroll() {
    var key = "note-comment-scroll:" + window.location.pathname;
    var saved = window.sessionStorage.getItem(key);
    if (saved !== null) {
      window.sessionStorage.removeItem(key);
      var y = parseInt(saved, 10);
      if (!isNaN(y)) {
        window.requestAnimationFrame(function () {
          window.requestAnimationFrame(function () { window.scrollTo(0, y); });
        });
      }
    }

    section.querySelectorAll('form[action$="/comments/"]').forEach(function (commentForm) {
      if (window.htmx && commentForm.hasAttribute("hx-post")) return;
      commentForm.addEventListener("submit", function () {
        window.sessionStorage.setItem(key, String(window.scrollY));
      });
    });
  }

  function armNameEditors() {
    section.querySelectorAll("[data-name-field]").forEach(function (field) {
      var form = field.closest("form");
      var summary = form && form.querySelector("[data-name-summary]");
      var edit = summary && summary.querySelector("[data-name-edit]");
      var display = summary && summary.querySelector("[data-name-display]");
      var input = field.querySelector('input[name="name"]');
      var accept = field.querySelector("[data-name-accept]");
      var cancel = field.querySelector("[data-name-cancel]");
      if (!form || !summary || !edit || !display || !input || !accept || !cancel) return;

      function close() {
        field.hidden = true;
        summary.hidden = false;
      }

      edit.addEventListener("click", function () {
        summary.hidden = true;
        field.hidden = false;
        input.focus();
        input.select();
      });
      accept.addEventListener("click", function () {
        var name = input.value.trim();
        if (!name) {
          input.focus();
          return;
        }
        input.value = name;
        input.dataset.savedName = name;
        display.textContent = name;
        close();
      });
      cancel.addEventListener("click", function () {
        input.value = input.dataset.savedName;
        close();
      });
    });
  }

  // ---- boot / HTMX reinitialization -----------------------------------------

  function updateEmptyState() {
    var hasComments = section.dataset.hasComments === "true";
    var layout = section.closest(".note-comments-layout");
    if (layout) layout.classList.toggle("note-comments-layout--empty", !hasComments);
    var header = document.querySelector("[data-page-header-container]");
    if (header && header.classList.contains("note-header-width--comments")) {
      header.classList.toggle("note-header-width--empty", !hasComments);
    }
  }

  function initializeSection() {
    if (threadObserver) threadObserver.disconnect();
    section = document.getElementById("comments");
    if (!section) return;
    threadList = section.querySelector("[data-comment-thread-list]");
    form = section.querySelector("form[data-comment-form]");
    chip = form && form.querySelector("[data-anchor-chip]");
    chipText = form && form.querySelector("[data-anchor-text]");

    unwrap(Array.prototype.slice.call(body.querySelectorAll("mark.comment-highlight")));
    pendingMarks = [];

    armDeleteForms();
    armReplyCards();
    armEnterToSubmit();
    armCommentComposer();
    preserveCommentScroll();
    armNameEditors();
    resolveAll();
    watchThreadLayout();
    scheduleThreadLayout();
    updateEmptyState();

    if (form && chip) {
      form.querySelector("[data-anchor-clear]").addEventListener("click", clearAnchor);
      if (field("quote").value) {
        // Re-rendered after a failed submission: keep the selection visible.
        showChip(field("quote").value);
        var offset = parseInt(field("start_offset").value, 10);
        var hit = Anchors.resolve(textOf(segments()), {
          quote: field("quote").value,
          prefix: field("prefix").value,
          suffix: field("suffix").value,
          offset: isNaN(offset) ? null : offset,
        });
        if (hit) pendingMarks = highlight(hit.start, hit.end, "pending", "is-pending");
      }
    }
  }

  initializeSection();

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail.target && event.detail.target.id === "comments") {
      initializeSection();
    }
  });

  var target = /^#comment-(\d+)$/.exec(window.location.hash);
  if (target) flash(target[1]);
})();
