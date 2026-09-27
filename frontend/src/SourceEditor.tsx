import Editor, { loader, OnMount } from "@monaco-editor/react";
import * as monaco from "monaco-editor/esm/vs/editor/editor.api";
import "monaco-editor/esm/vs/editor/edcore.main";
import "monaco-editor/esm/vs/basic-languages/xml/xml.contribution";
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import { useEffect, useRef } from "react";
import type { Diagnostic } from "./api";

/** A problem located in the source, with an optional verified fix. */
export interface SrcMarker {
  diag: Diagnostic;
  start?: number; end?: number;          // exact offsets when known
  fix?: { label: string; start: number; end: number; text: string };
}

// Quick fixes for the lightbulb, per model. Registered once for the XML language.
const fixesByModel = new Map<string, SrcMarker[]>();
let providerRegistered = false;
function registerQuickFixes() {
  if (providerRegistered) return;
  providerRegistered = true;
  monaco.languages.registerCodeActionProvider("xml", {
    provideCodeActions(model, range) {
      const list = fixesByModel.get(model.uri.toString()) ?? [];
      const actions = list.filter((m) => m.fix).filter((m) => {
        const a = model.getPositionAt(m.fix!.start), b = model.getPositionAt(m.fix!.end);
        return monaco.Range.areIntersectingOrTouching(range, new monaco.Range(a.lineNumber, a.column, b.lineNumber, b.column));
      }).map((m) => {
        const a = model.getPositionAt(m.fix!.start), b = model.getPositionAt(m.fix!.end);
        return {
          title: m.fix!.label, kind: "quickfix", isPreferred: true,
          edit: { edits: [{ resource: model.uri, versionId: model.getVersionId(),
            textEdit: { range: new monaco.Range(a.lineNumber, a.column, b.lineNumber, b.column), text: m.fix!.text } }] },
        } as monaco.languages.CodeAction;
      });
      return { actions, dispose() {} };
    },
  });
}

// Bundle Monaco locally: no CDN, works offline.
(self as any).MonacoEnvironment = { getWorker: () => new EditorWorker() };
loader.config({ monaco });

const sev = (s: string) => s === "warning" ? monaco.MarkerSeverity.Warning : s === "info" ? monaco.MarkerSeverity.Info : monaco.MarkerSeverity.Error;

export interface SourceProps {
  text: string;
  markers: SrcMarker[];
  reveal: { line: number; endLine?: number; n: number } | null;
  onChange: (text: string) => void;
  onCursor: (offset: number) => void;
  theme: "light" | "dark";
}

export function SourceEditor(p: SourceProps) {
  const ed = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  const deco = useRef<monaco.editor.IEditorDecorationsCollection | null>(null);
  const props = useRef(p);
  props.current = p;
  const applying = useRef(false);

  const onMount: OnMount = (editor) => {
    ed.current = editor as any;
    registerQuickFixes();
    deco.current = editor.createDecorationsCollection();
    editor.onDidChangeModelContent(() => { if (!applying.current) props.current.onChange(editor.getValue()); });
    editor.onDidChangeCursorPosition((e) => {
      if (e.source === "api") return;
      const m = editor.getModel(); if (m) props.current.onCursor(m.getOffsetAt(e.position));
    });
    sync();
    applyMarkers();     // markers must also appear when the editor opens after validation ran
  };

  // external text changes (visual edits, restore) keep Monaco's undo stack
  const sync = () => {
    const editor = ed.current; const m = editor?.getModel();
    if (!editor || !m) return;
    if (m.getValue() !== props.current.text) {
      applying.current = true;
      m.pushEditOperations([], [{ range: m.getFullModelRange(), text: props.current.text }], () => null);
      applying.current = false;
    }
  };
  useEffect(sync, [p.text]);

  const applyMarkers = () => {
    const m = ed.current?.getModel(); if (!m) return;
    const lines = m.getLineCount();
    fixesByModel.set(m.uri.toString(), props.current.markers);
    monaco.editor.setModelMarkers(m, "asthra", props.current.markers.filter((x) => x.start !== undefined || x.diag.line).map((x) => {
      const d = x.diag;
      let sl: number, sc: number, el: number, ec: number;
      if (x.start !== undefined && x.end !== undefined && x.end <= m.getValueLength()) {
        const a = m.getPositionAt(x.start), b = m.getPositionAt(Math.max(x.end, x.start + 1));
        [sl, sc, el, ec] = [a.lineNumber, a.column, b.lineNumber, b.column];
      } else {
        sl = el = Math.min(d.line!, lines); sc = m.getLineFirstNonWhitespaceColumn(sl) || 1; ec = m.getLineMaxColumn(sl);
      }
      const hint = [d.suggestion, x.fix ? `Quick fix available (Ctrl+.): ${x.fix.label}` : ""].filter(Boolean).join("\n");
      return { severity: sev(d.severity), message: `${d.message}${hint ? "\n" + hint : ""}`, source: "ASTHRA",
        code: d.rule_id, startLineNumber: sl, startColumn: sc, endLineNumber: el, endColumn: ec };
    }));
  };
  useEffect(applyMarkers, [p.markers, p.text]);

  useEffect(() => {
    const editor = ed.current; if (!editor || !p.reveal) return;
    const end = p.reveal.endLine ?? p.reveal.line;
    editor.revealLinesInCenter(p.reveal.line, end);
    editor.setPosition({ lineNumber: p.reveal.line, column: 1 });
    deco.current?.set([{ range: new monaco.Range(p.reveal.line, 1, end, 1), options: { isWholeLine: true, className: "src-focus" } }]);
  }, [p.reveal]);

  return (
    <Editor
      defaultLanguage="xml" defaultValue={p.text} onMount={onMount} theme={p.theme === "dark" ? "vs-dark" : "vs"}
      options={{ minimap: { enabled: false }, fontSize: 13, fontFamily: "'Cascadia Code', Consolas, 'Courier New', monospace",
        wordWrap: "on", scrollBeyondLastLine: false, renderWhitespace: "boundary", tabSize: 2, automaticLayout: true, glyphMargin: true }}
    />
  );
}
