import { Pipe, PipeTransform, inject } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import DOMPurify from 'dompurify';
import hljs from 'highlight.js';
import katex from 'katex';
import { marked } from 'marked';

marked.use({
  renderer: {
    code({ text, lang }) {
      const language = lang && hljs.getLanguage(lang) ? lang : undefined;
      const highlighted = language
        ? hljs.highlight(text, { language }).value
        : hljs.highlightAuto(text).value;
      const langClass = language ? ` language-${language}` : '';
      return `<pre><code class="hljs${langClass}">${highlighted}</code></pre>`;
    },
  },
});
marked.setOptions({ breaks: true });

// $$...$$ (block) must be tried before $...$ (inline) so a block formula's
// dollar signs aren't consumed as two separate inline matches first.
const MATH_BLOCK = /\$\$([\s\S]+?)\$\$/g;
const MATH_INLINE = /\$([^$\n]+?)\$/g;

function katexToHtml(expr: string, displayMode: boolean): string {
  try {
    return katex.renderToString(expr.trim(), { throwOnError: false, displayMode, output: 'html' });
  } catch {
    return displayMode ? `$$${expr}$$` : `$${expr}$`;
  }
}

/**
 * Renders LLM chat output: math ($…$/$$…$$, via KaTeX) is extracted into
 * placeholder tokens before markdown parsing so `marked` can't mangle LaTeX
 * syntax (e.g. underscores read as emphasis), then swapped back in after.
 * The final HTML is DOMPurify-sanitized before any caller may bypass Angular's
 * sanitizer with it — content originates from a local LLM, not a trusted
 * backend, so it must not be trusted as-is.
 */
export function renderChatMarkdown(raw: string): string {
  const placeholders: string[] = [];
  const stash = (html: string) => {
    const token = `@@MATH${placeholders.length}@@`;
    placeholders.push(html);
    return token;
  };

  let text = raw.replace(MATH_BLOCK, (_m, expr) => stash(katexToHtml(expr, true)));
  text = text.replace(MATH_INLINE, (_m, expr) => stash(katexToHtml(expr, false)));

  let html = marked.parse(text, { async: false }) as string;
  html = html.replace(/@@MATH(\d+)@@/g, (_m, i) => placeholders[Number(i)]);

  return DOMPurify.sanitize(html);
}

@Pipe({ name: 'chatMarkdown' })
export class ChatMarkdownPipe implements PipeTransform {
  private readonly sanitizer = inject(DomSanitizer);

  transform(content: string | null | undefined): SafeHtml {
    if (!content) return '';
    return this.sanitizer.bypassSecurityTrustHtml(renderChatMarkdown(content));
  }
}
