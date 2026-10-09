import type { Numbering } from "./adm";
// Thin client for the local ASTHRA API. Write calls carry X-Asthra (CSRF guard).
export interface Diagnostic {
  stage: number; severity: "fatal" | "error" | "warning" | "info"; rule_id: string; message: string;
  source_file?: string; element_path?: string | null; line?: number | null; column?: number | null;
  suggestion?: string | null; reference?: string | null;
  attribute?: string | null; value?: string | null; raw_message?: string | null;
  fix?: { label: string; kind: "attr" | "text" | "insert"; attribute?: string | null; value: string;
    element?: string | null; position?: "before" | "end" | null } | null;
  category?: string | null;
  consequence_of?: string | null;
}
export interface StageResult { stage: number; status: string; note: string }
export interface Report {
  statuses: Record<"structural" | "business_rules" | "references" | "engineering", string>;
  counts: Record<string, number>; stages: StageResult[]; diagnostics: Diagnostic[];
  package_id?: string | null;
  entities?: Record<string, string>;
  rendered_xml?: string | null;
  render_note?: string | null;
}
export interface OutlineNode { name: string; path: string; line: number; label: string; children: OutlineNode[] }
export interface Outline { root: OutlineNode; truncated: boolean; count: number }
export interface Project { id: string; name: string; document_count: number; root_path: string }
export interface Doc {
  id: string; project_id: string; original_name: string; syntax: string; standard: string | null; issue: string | null;
  doc_type: string | null; package_id: string | null; sha256: string; size_bytes: number;
  identity: { display?: string; fields?: Record<string, string>; warnings?: string[] };
  identification: { status: string; notes: string[]; selection?: string;
    candidates: { package_id: string; doc_type: string }[]; compatible?: { package_id: string; doc_type: string }[] };
  last_validation: { structural_status: string } | null; has_working_copy: boolean; revision_count: number;
}
export interface Revision { id: string; number: number; message: string; structural_status: string; created_at: string; sha256: string }
export interface Pkg {
  id: string; name: string; standard: string; issue: string; provenance: string; enabled: boolean; documents?: number; checksum?: string;
  doc_types: { id: string; label: string; content_family: string }[]; licence_note: string;
}
export interface RenderProfile { profile: string; roles: Record<string, string>; labels: Record<string, string>; default_text: string;
  numbering?: Numbering | null; columns?: Record<string, string[]> }
export interface Proposal {
  kind: "package" | "s1000d" | "dtd" | "sgml" | "xsd"; standard?: string | null; issue?: string | null; name?: string | null;
  notes: string[]; path?: string;
  folders?: { path: string; issue: string | null; doc_types: string[]; files: number; patch: string }[];
  folder?: string | null; entity_folders?: { path: string; files: number; patch: string }[]; entity_folder?: string | null;
  default_types?: string[]; types?: string[]; aliases?: string[]; missing_files?: string[];
  doc_types?: { id: string; label?: string; schema_file?: string; root?: string | null; root_candidates?: string[];
    namespace?: string | null; selected?: boolean; problem?: string | null; public_id?: string | null }[];
}
export interface Inspect { staging_id: string; proposal: Proposal; installed: string[] }

export interface DocState { document: Doc; origin: string; text: string; revisions: Revision[]; render: RenderProfile }
export interface SchemaOption { package_id: string; doc_type: string; label: string; standard: string; issue: string; provenance: string; declared: boolean }
export interface Check { report: Report; outline: Outline | null }

async function call<T>(method: string, url: string, body?: unknown, form?: FormData): Promise<T> {
  const headers: Record<string, string> = { "X-Asthra": "1" };
  let payload: BodyInit | undefined;
  if (form) payload = form;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  const r = await fetch(url, { method, headers, body: payload });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* keep */ }
    throw new Error(msg);
  }
  return r.json();
}

export interface KSummary { counts: Record<string, number>; sources: { kind: string; n: number; last: string }[]; findings: number }
export interface KPart { id: number; part_number: string; manufacturer_code: string; name: string | null; part_type: string;
  tasks: number; data_modules: number; catalogue: number; superseded_by: string | null; source: string | null }
export interface KFinding { rule: string; subject: string; message: string; values: Record<string, unknown> }
export interface KImport { imported: { file: string; dmc: string; title: string; kind?: string; note?: string; [count: string]: any }[];
  skipped: { file: string; reason: string }[] }

export interface BrexEntry { dmc: string; issue: string; title: string; schema_issue: string | null; parent_dmc: string | null;
  rules: number; sns_systems: number; file: string; source_name: string; installed_at: string }

export interface TrSchema { package_id: string; doc_type: string; label: string; standard: string; issue: string; saved: boolean; record: string | null; error?: string }
export interface TrField { path: string; format?: string; confidence?: number }
export interface TrBinding { concept: string; root: string; record: string | null; container: string[] | null;
  group: { level: number; element: string; attr: string; field?: string; confidence?: number } | null;
  fields: Record<string, TrField>; problems?: string[]; alternatives?: string[]; saved_at?: string; constants?: Record<string, string> }
export interface TrSlot { path: string; leaf: string; kind: string; parent: string; required: boolean }
export interface TrBindingView { package_id: string; doc_type: string; binding: TrBinding; saved: boolean; check: string[];
  candidates: { record: string; score: number; fields: number }[]; slots: TrSlot[];
  group_options: { level: number; element: string; attr: string }[]; formats: { id: string; label: string }[];
  concept: { id: string; label: string; fields: { id: string; label: string }[] }; schema_kind: string }
export interface TrRules { exclude: string[]; exclude_property: string[]; skip_zero_quantity: boolean; numbering: string; figure: string;
  omit_cage: string[]; omit_unit: string[]; max_depth: number; uppercase_names: boolean }
export type TrSource = { kind: "engineering"; tops: string[] } | { kind: "catalogue"; source_id: number; figure: string; renumber_figure?: boolean }
export interface TrResult { report: { written: number; groups: { figure: string; lines: number; replaced: number }[]; warnings: string[]; problems: string[] };
  excluded: any[]; records: number; document: { id: string; name: string; structural: string; errors: string[] } | null }

export interface XrView { id: string; label: string; kind: string; standard?: string }
export interface XrModel { label: string; spec: string; issue: string; file: string; classes: number; common: number; attributes: number; hints?: string[] }
export interface XrOverview { models: XrModel[]; views: XrView[]; terms: number; classes: number; core: number; subjects: Record<string, string> }
export interface XrName { tag: string; path?: string; from: string; all?: string[]; others?: string[] }
export interface XrTerm { id: string; label: string; class: string; doc: string; key: boolean; common: boolean; core: string; origin: string; names: Record<string, string> }
export interface XrValue { term: string; value: string; context: string; source: { kind: string; document: string }; read_as: string | null; source_column: string | null }
export interface XrRow { term: string; label: string; doc: string; core: string; name: XrName | null; values: XrValue[]; conflict: boolean }
export interface XrItem { subject: string; subject_label: string; key: string; view: string; rows: XrRow[]; not_in_view: XrRow[] }

export interface XrCoverageRow { standard: string; label: string; status: "ok" | "review" | "missing"; crosswalk: boolean; s_series: boolean; hub?: boolean;
  schemas: { view: string; label: string; placed?: number; of?: number; confirmed?: number; review?: number; error?: string }[];
  model: XrModel | null; documents: number; unidentified: string[]; unchosen?: string[]; library: number;
  actions: { do: "install_schema" | "add_model" | "review" | "choose_schema"; label: string; why?: string; view?: string;
    package_id?: string; doc_type?: string; ids?: string[]; certain?: boolean }[];
  where: { url: string; what: string } | null }
export interface XrWaiting { id: string; ids: string[]; name: string; projects: string[]; standard: string | null; message: string; url?: string | null;
  needs?: string[]; choose?: { package_id: string; doc_type: string; text: string; declared: boolean } }
export interface XrReviewRow { term: string; label: string; group: string; doc: string; status: "confirmed" | "ok" | "review" | "missing" | "none";
  placement: XrName | null; candidates: string[] }
export interface XrReview { view: string; label: string; rows: XrReviewRow[]; counts: Record<string, number>; applied_elsewhere?: number }

export const api = {
  projects: () => call<Project[]>("GET", "/api/projects"),
  brexList: () => call<BrexEntry[]>("GET", "/api/brex"),
  brexAdd: (file: File) => { const f = new FormData(); f.append("file", file); return call<BrexEntry>("POST", "/api/brex", undefined, f); },
  brexSubstitutes: () => call<Record<string, string>>("GET", "/api/brex/substitutes"),
  brexSetSubstitute: (named: string, use: string) => call<Record<string, string>>("POST", "/api/brex/substitutes", { named, use }),
  brexRemoveSubstitute: (named: string) => call<Record<string, string>>("DELETE", `/api/brex/substitutes/${encodeURIComponent(named)}`),
  brexRemove: (dmc: string, issue: string) => call<{ ok: boolean }>("DELETE", `/api/brex/${encodeURIComponent(dmc)}/${encodeURIComponent(issue)}`),
  kSummary: () => call<KSummary>("GET", "/api/knowledge/summary"),
  kImportProject: (pid: string) => call<KImport>("POST", `/api/knowledge/import-project/${pid}`),
  kEngineeringSet: (files: File[]) => {
    const f = new FormData();
    for (const x of files) f.append("files", x, (x as any).webkitRelativePath || x.name);
    return call<KImport>("POST", "/api/knowledge/engineering-set", undefined, f);
  },
  kEngineering: (file: File) => { const f = new FormData(); f.append("file", file); return call<KImport>("POST", "/api/knowledge/engineering", undefined, f); },
  kModels: () => call<any[]>("GET", "/api/knowledge/models"),
  kAddModel: (file: File) => { const f = new FormData(); f.append("file", file); return call<{ id: number; name: string; nodes: number; linked: number }>("POST", "/api/knowledge/models", undefined, f); },
  kDeleteModel: (id: number) => call<{ ok: boolean }>("DELETE", `/api/knowledge/models/${id}`),
  kModelStatus: (id: number) => call<Record<string, any>>("GET", `/api/knowledge/models/${id}/status`),
  kLocate: (pn: string) => call<{ model_id: number; model: string; nodes: string[] }[]>("GET", `/api/knowledge/locate?pn=${encodeURIComponent(pn)}`),
  kBike: () => call<{ loaded: boolean; reason?: string }>("POST", "/api/knowledge/examples/bike"),
  kReset: () => call<{ ok: boolean }>("DELETE", "/api/knowledge"),
  kParts: (q = "", kind = "") => call<KPart[]>("GET", `/api/knowledge/parts?q=${encodeURIComponent(q)}&kind=${encodeURIComponent(kind)}`),
  kPart: (id: number) => call<any>("GET", `/api/knowledge/parts/${id}`),
  kBreakdown: () => call<any[]>("GET", "/api/knowledge/breakdown"),
  kTasks: () => call<any[]>("GET", "/api/knowledge/tasks"),
  kTask: (id: string, rev: string) => call<any>("GET", `/api/knowledge/tasks/${encodeURIComponent(id)}/${encodeURIComponent(rev)}`),
  kDataModules: (q = "") => call<any[]>("GET", `/api/knowledge/data-modules?q=${encodeURIComponent(q)}`),
  kDataModule: (dmc: string) => call<any>("GET", `/api/knowledge/data-modules/${encodeURIComponent(dmc)}`),
  kFindings: () => call<KFinding[]>("GET", "/api/knowledge/findings"),
  kSources: () => call<any[]>("GET", "/api/knowledge/sources"),
  xrCoverage: () => call<{ standards: XrCoverageRow[]; waiting: XrWaiting[] }>("GET", "/api/crossref/coverage"),
  xrHints: (standard = "") => call<string[]>("GET", `/api/crossref/hints?standard=${encodeURIComponent(standard)}`),
  xrDocHint: (did: string) => call<{ message?: string; url?: string; label?: string }>("GET", `/api/crossref/doc-hint/${did}`),
  xrReview: (view: string) => call<XrReview>("GET", `/api/crossref/review?view=${encodeURIComponent(view)}`),
  xrConfirmMany: (package_id: string, doc_type: string, items: { term: string; path: string }[]) =>
    call<XrReview>("PUT", "/api/crossref/review", { package_id, doc_type, items }),
  xrAssignSchemas: (items: { doc_id: string; package_id: string; doc_type: string }[]) =>
    call<{ assigned: number; failed: { doc_id: string; error: string }[] }>("POST", "/api/crossref/assign-schemas", { items }),
  xrOverview: () => call<XrOverview>("GET", "/api/crossref/overview"),
  xrAddModel: (file: File) => { const f = new FormData(); f.append("file", file); return call<XrModel>("POST", "/api/crossref/models", undefined, f); },
  xrDeleteModel: (label: string) => call<{ ok: boolean }>("DELETE", `/api/crossref/models?label=${encodeURIComponent(label)}`),
  xrTerms: (q: string, core: boolean) => call<XrTerm[]>("GET", `/api/crossref/terms?q=${encodeURIComponent(q)}&core=${core}`),
  xrTerm: (id: string) => call<any>("GET", `/api/crossref/term?id=${encodeURIComponent(id)}`),
  xrConfirm: (package_id: string, doc_type: string, term: string, path: string) => call<any>("PUT", "/api/crossref/name", { package_id, doc_type, term, path }),
  xrSubjects: (q: string) => call<{ subject: string; key: string; label: string; name: string; detail?: string }[]>("GET", `/api/crossref/subjects?q=${encodeURIComponent(q)}`),
  xrItem: (subject: string, key: string, view: string) =>
    call<XrItem>("GET", `/api/crossref/item?subject=${encodeURIComponent(subject)}&key=${encodeURIComponent(key)}&view=${encodeURIComponent(view)}`),
  trSchemas: () => call<TrSchema[]>("GET", "/api/translate/schemas"),
  trBinding: (package_id: string, doc_type: string, record?: string) =>
    call<TrBindingView>("GET", `/api/translate/binding?package_id=${encodeURIComponent(package_id)}&doc_type=${encodeURIComponent(doc_type)}${record ? `&record=${encodeURIComponent(record)}` : ""}`),
  trSaveBinding: (package_id: string, doc_type: string, binding: TrBinding) => call<TrBindingView>("PUT", "/api/translate/binding", { package_id, doc_type, binding }),
  trForgetBinding: (package_id: string, doc_type: string) =>
    call<{ ok: boolean }>("DELETE", `/api/translate/binding?package_id=${encodeURIComponent(package_id)}&doc_type=${encodeURIComponent(doc_type)}`),
  trRules: () => call<TrRules>("GET", "/api/translate/rules"),
  trSaveRules: (r: TrRules) => call<TrRules>("PUT", "/api/translate/rules", r),
  trSources: () => call<{ assemblies: any[]; parts_lists: any[] }>("GET", "/api/translate/sources"),
  trTargets: (pid: string) => call<any[]>("GET", `/api/translate/targets/${pid}`),
  trPreview: (source: TrSource, rules: TrRules) => call<{ records: any[]; excluded: any[] }>("POST", "/api/translate/preview", { source, rules }),
  trGenerate: (doc_id: string, source: TrSource, rules: TrRules, binding?: TrBinding) =>
    call<TrResult>("POST", "/api/translate/generate", { doc_id, source, rules, binding }),
  createProject: (name: string) => call<Project>("POST", "/api/projects", { name }),
  documents: (pid: string) => call<Doc[]>("GET", `/api/projects/${pid}/documents`),
  importDocument: (pid: string, file: File) => { const f = new FormData(); f.append("file", file); return call<Doc>("POST", `/api/projects/${pid}/documents`, undefined, f); },
  state: (did: string) => call<DocState>("GET", `/api/documents/${did}/state`),
  check: (did: string, text: string) => call<Check>("POST", `/api/documents/${did}/check`, { text }),
  save: (did: string, text: string) => call<Check>("PUT", `/api/documents/${did}/working`, { text }),
  discard: (did: string) => call<DocState>("DELETE", `/api/documents/${did}/working`),
  deleteDocument: (did: string) => call<{ id: string; name: string }>("DELETE", `/api/documents/${did}`),
  deleteDocuments: (ids: string[]) => call<{ deleted: { id: string; name: string }[]; failed: { id: string; error: string }[] }>("POST", "/api/documents/delete", { ids }),
  commit: (did: string, message: string) => call<Revision>("POST", `/api/documents/${did}/revisions`, { message }),
  restore: (did: string, rid: string) => call<Check>("POST", `/api/documents/${did}/revisions/${rid}/restore`),
  schemaModel: (did: string) => call<import("./schemaModel").SchemaModel>("GET", `/api/documents/${did}/schema-model`),
  schemaOptions: (did: string) => call<SchemaOption[]>("GET", `/api/documents/${did}/schema-options`),
  chooseSchema: (did: string, package_id: string, doc_type_id: string) => call<DocState>("PUT", `/api/documents/${did}/schema`, { package_id, doc_type_id }),
  packages: () => call<Pkg[]>("GET", "/api/registry/packages"),
  installPackage: (file: File) => { const f = new FormData(); f.append("file", file); return call<Pkg>("POST", "/api/registry/packages", undefined, f); },
  setEnabled: (id: string, enabled: boolean) => call<Pkg>("POST", `/api/registry/packages/${id}/enabled`, { enabled }),
  inspectSchemas: (files: File[]) => {
    const f = new FormData();
    for (const file of files) f.append("files", file, (file as any).webkitRelativePath || file.name);
    return call<Inspect>("POST", "/api/registry/inspect", undefined, f);
  },
  buildSchemas: (staging_id: string, choice: Proposal, replace: boolean) =>
    call<Pkg & { action: string }>("POST", "/api/registry/build", { staging_id, choice, replace }),
  removePackage: (key: string, force: boolean) => call<{ unlinked_documents: number }>("DELETE", `/api/registry/packages/${key}?force=${force}`),
  importSet: (file: File) => { const f = new FormData(); f.append("file", file); return call<{ results: { id: string; result: string }[] }>("POST", "/api/registry/import-set", undefined, f); },
  exportPackageUrl: (key: string) => `/api/registry/packages/${key}/export`,
  exportSetUrl: () => "/api/registry/export-set",
  loadSamples: () => call<Project>("POST", "/api/samples"),
  exportUrl: (did: string, what: "current" | "original" | "revision", rid?: string) =>
    `/api/documents/${did}/export?what=${what}${rid ? `&rid=${rid}` : ""}`,
};
