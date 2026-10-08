import { ReactNode, useEffect } from "react";
import type { HeaderInfo } from "./adm";

/** One page of paper: the title block read from the document, the document itself, and
 *  the end-of-module line. Always light, like a PDF, whatever the app theme. */
export function Sheet({ info, standardLine, children }: { info: HeaderInfo | null; standardLine?: string; children: ReactNode }) {
  const end = info?.kind === "s1000d" ? "End of data module" : "End of document";
  return (
    <div lang="en" className={`sheet${info && info.kind !== "generic" ? " has-header" : ""}`}>
      {info && info.kind !== "generic" && (
        <header className="doc-head">
          <div className="dh-top">
            <span className="dh-code">{info.code}</span>
            <span className="dh-issue">{[info.issue, info.date].filter(Boolean).join("  ·  ")}</span>
          </div>
          {info.title && <h1 className="dh-title">{info.title}</h1>}
          {info.subtitle && <div className="dh-sub">{info.subtitle}</div>}
          <dl className="dh-facts">
            {info.applic && <div><dt>Applicable to</dt><dd>{info.applic}</dd></div>}
            {info.security && <div><dt>Security classification</dt><dd>{info.security}</dd></div>}
            {standardLine && <div><dt>Standard</dt><dd>{standardLine}</dd></div>}
          </dl>
        </header>
      )}
      {children}
      <footer className="doc-foot"><span>{end}</span>{info?.code && <span className="dh-code">{info.code}</span>}</footer>
    </div>
  );
}

const q = (s: string) => `"${s.replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, " ")}"`;

/** Running header and footer for printed / PDF pages (CSS paged media margin boxes). */
export function usePrintPage(info: HeaderInfo | null, fallbackTitle: string) {
  useEffect(() => {
    let el = document.getElementById("asthra-page") as HTMLStyleElement | null;
    if (!el) { el = document.createElement("style"); el.id = "asthra-page"; document.head.appendChild(el); }
    const title = (info?.title ?? fallbackTitle).slice(0, 70);
    const left = info?.code ?? "";
    const issue = [info?.issue, info?.date].filter(Boolean).join("  ·  ");
    el.textContent = `@page {
      size: A4; margin: 22mm 17mm 20mm 17mm; background: #fff;
      @top-left { content: ${q(left)}; font: 500 8pt "IBM Plex Mono", monospace; color: #444; }
      @top-right { content: ${q(title)}; font: 600 8pt "IBM Plex Sans", sans-serif; color: #444; }
      @bottom-left { content: ${q(issue)}; font: 400 8pt "IBM Plex Sans", sans-serif; color: #555; }
      @bottom-right { content: "Page " counter(page) " of " counter(pages); font: 400 8pt "IBM Plex Sans", sans-serif; color: #555; }
    }`;
  }, [info, fallbackTitle]);
}
