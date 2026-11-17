// Minimal, safe Markdown renderer for assistant answers: text is HTML-escaped first, and only
// http(s) links survive. Supports headings, lists, blockquotes, fenced/inline code, bold,
// italics, links, tables, and [n] citations (rendered as links to the numbered source).
"use strict";

(function () {
  const escapeHtml = (s) =>
    s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  function inline(text, citations) {
    const codes = [];
    let out = escapeHtml(text).replace(/`([^`]+)`/g, (_, code) => {
      codes.push(code);
      return `\u0000${codes.length - 1}\u0000`;
    });
    out = out
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, "$1<em>$2</em>")
      .replace(/\[(\d{1,2})\]/g, (match, n) => {
        const source = citations[n];
        return source
          ? `<a class="cite" href="${escapeHtml(source.url)}" target="_blank" rel="noopener" title="${escapeHtml(source.title)}">[${n}]</a>`
          : match;
      });
    return out.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[i]}</code>`);
  }

  function table(lines, citations) {
    const cells = (line) => line.trim().replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim(), citations));
    const [head, , ...rows] = lines;
    const th = cells(head).map((c) => `<th>${c}</th>`).join("");
    const body = rows.map((r) => `<tr>${cells(r).map((c) => `<td>${c}</td>`).join("")}</tr>`).join("");
    return `<div class="table-wrap"><table><thead><tr>${th}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  function render(markdown, sources) {
    const citations = {};
    for (const s of sources || []) citations[s.number] = s;
    const lines = markdown.replace(/\r\n/g, "\n").split("\n");
    const html = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (/^\s*(```|~~~)/.test(line)) {
        const fence = line.trim().slice(0, 3);
        const code = [];
        for (i++; i < lines.length && !lines[i].trim().startsWith(fence); i++) code.push(lines[i]);
        html.push(`<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`);
        i++;
      } else if (/^#{1,6}\s/.test(line)) {
        const level = Math.min(line.match(/^#+/)[0].length + 2, 6); // keep below the page's h1/h2
        html.push(`<h${level}>${inline(line.replace(/^#+\s*/, ""), citations)}</h${level}>`);
        i++;
      } else if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1] || "")) {
        const block = [];
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) block.push(lines[i++]);
        html.push(table(block, citations));
      } else if (/^\s*>/.test(line)) {
        const block = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) block.push(lines[i++].replace(/^\s*>\s?/, ""));
        html.push(`<blockquote>${render(block.join("\n"), sources)}</blockquote>`);
      } else if (/^\s*([-*+]|\d+[.)])\s/.test(line)) {
        const ordered = /^\s*\d/.test(line);
        const items = [];
        while (i < lines.length && /^\s*([-*+]|\d+[.)])\s/.test(lines[i])) {
          items.push(`<li>${inline(lines[i].replace(/^\s*([-*+]|\d+[.)])\s+/, ""), citations)}</li>`);
          i++;
        }
        html.push(ordered ? `<ol>${items.join("")}</ol>` : `<ul>${items.join("")}</ul>`);
      } else if (!line.trim()) {
        i++;
      } else {
        const para = [];
        while (i < lines.length && lines[i].trim() && !/^(\s*(```|~~~|>|[-*+]\s|\d+[.)]\s|\|)|#{1,6}\s)/.test(lines[i])) {
          para.push(lines[i++]);
        }
        if (!para.length) para.push(lines[i++]);
        html.push(`<p>${inline(para.join("\n"), citations).replace(/\n/g, "<br>")}</p>`);
      }
    }
    return html.join("");
  }

  window.renderMarkdown = render;
  window.escapeHtml = escapeHtml;
})();
