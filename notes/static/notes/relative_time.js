(function () {
  "use strict";

  function label(date) {
    var seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
    if (seconds < 60) return "just now";
    if (seconds < 3600) return Math.floor(seconds / 60) + "m ago";
    if (seconds < 86400) return Math.floor(seconds / 3600) + "h ago";
    if (seconds < 604800) return Math.floor(seconds / 86400) + "d ago";
    if (seconds < 2592000) return Math.floor(seconds / 604800) + "w ago";
    if (seconds < 31536000) return Math.floor(seconds / 2592000) + "mo ago";
    return Math.floor(seconds / 31536000) + "y ago";
  }

  function refresh() {
    document.querySelectorAll("time[data-relative-time]").forEach(function (time) {
      var date = new Date(time.dateTime);
      if (isNaN(date.getTime())) return;
      time.textContent = label(date);
      time.title = date.toLocaleString();
    });
  }

  refresh();
  setInterval(refresh, 60000);
})();
