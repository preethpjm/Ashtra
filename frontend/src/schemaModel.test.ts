import { describe, expect, it } from "vitest";
import { fillTemplate, inlineAllowed, insertable, isCompletable, isValid, SchemaModel, template } from "./schemaModel";

// a small model shaped like an S1000D procedure (from the synthetic XSD)
const el = (n: string, min = 1, max: number | null = 1) => ({ k: "el" as const, n, min, max });
const M: SchemaModel = {
  root: "procedure", kind: "xsd", elements: {
    procedure: { content: { k: "seq", items: [el("preliminaryRqmts"), el("mainProcedure"), el("closeRqmts")], min: 1, max: 1 }, mixed: false, empty: false, any: false, text: false, attrs: [], inclusions: [], exclusions: [] },
    mainProcedure: { content: el("proceduralStep", 1, null), mixed: false, empty: false, any: false, text: false, attrs: [], inclusions: [], exclusions: [] },
    proceduralStep: { content: { k: "seq", min: 1, max: 1, items: [
      { k: "choice", min: 0, max: null, items: [el("warning"), el("caution"), el("note")] }, el("para"), el("figure", 0, 1), el("proceduralStep", 0, null)] },
      mixed: false, empty: false, any: false, text: false, attrs: [{ name: "id", required: false, kind: "id", values: [], default: null, fixed: null }], inclusions: [], exclusions: [] },
    para: { content: { k: "choice", min: 0, max: null, items: [el("internalRef"), el("emphasis")] }, mixed: true, empty: false, any: false, text: false, attrs: [], inclusions: [], exclusions: [] },
    figure: { content: { k: "seq", min: 1, max: 1, items: [el("title"), el("graphic", 1, null)] }, mixed: false, empty: false, any: false, text: false,
      attrs: [{ name: "id", required: true, kind: "id", values: [], default: null, fixed: null }], inclusions: [], exclusions: [] },
    graphic: { content: null, mixed: false, empty: true, any: false, text: false, attrs: [{ name: "infoEntityIdent", required: true, kind: "entity", values: [], default: null, fixed: null }], inclusions: [], exclusions: [] },
    internalRef: { content: null, mixed: false, empty: true, any: false, text: false, attrs: [{ name: "internalRefId", required: true, kind: "idref", values: [], default: null, fixed: null }], inclusions: [], exclusions: [] },
    title: { content: null, mixed: false, empty: false, any: false, text: true, attrs: [], inclusions: [], exclusions: [] },
    warning: { content: el("para", 1, null), mixed: false, empty: false, any: false, text: false, attrs: [], inclusions: [], exclusions: [] },
  },
};

describe("content-model engine", () => {
  it("offers only what the schema allows at each position", () => {
    // in a step [para]: before para → admonitions; after para → figure or sub-step, never a table or a second para
    expect(insertable(M, "proceduralStep", ["para"], 0)).toEqual(["caution", "note", "warning"]);
    expect(insertable(M, "proceduralStep", ["para"], 1)).toEqual(["figure", "proceduralStep"]);
    expect(insertable(M, "proceduralStep", ["para", "figure"], 2)).toEqual(["proceduralStep"]);   // only one figure
    expect(insertable(M, "procedure", ["preliminaryRqmts", "mainProcedure", "closeRqmts"], 1)).toEqual([]);
    expect(insertable(M, "title", [], 0)).toEqual([]);                                             // text only
  });
  it("allows building step by step (completable) but checks exact validity", () => {
    expect(isCompletable(M, "procedure", ["mainProcedure"])).toBe(true);
    expect(isValid(M, "procedure", ["mainProcedure"])).toBe(false);
    expect(isCompletable(M, "procedure", ["closeRqmts", "mainProcedure"])).toBe(false);          // order is fixed
    expect(isValid(M, "proceduralStep", ["note", "para", "proceduralStep", "proceduralStep"])).toBe(true);
  });
  it("lists inline elements for mixed content", () => {
    expect(inlineAllowed(M, "para")).toEqual(["emphasis", "internalRef"]);
    expect(inlineAllowed(M, "proceduralStep")).toEqual([]);
  });
  it("builds minimal valid content with required attributes", () => {
    const used = new Set(["figure-0001"]);
    const t = template(M, "figure", used);
    expect(t.xml).toMatch(/^<figure id="figure-0002"><title><\/title><graphic infoEntityIdent="@@[\w-]+@@"\/><\/figure>$/);
    expect(t.needs.map((n) => n.attr.name)).toEqual(["infoEntityIdent"]);
    const filled = fillTemplate(t.xml, { [t.needs[0].id]: "ICN-X-1" });
    expect(filled).toContain('infoEntityIdent="ICN-X-1"');
    const step = template(M, "proceduralStep", new Set());
    expect(step.xml).toBe("<proceduralStep><para></para></proceduralStep>");                       // para is required
    const ref = template(M, "internalRef", new Set());
    expect(ref.needs[0].attr.kind).toBe("idref");                                                   // chosen from the document's IDs
  });
  it("applies SGML inclusions and exclusions from ancestors", () => {
    const S: SchemaModel = JSON.parse(JSON.stringify(M));
    S.elements.mainProcedure.inclusions = ["revst"];
    S.elements.revst = { content: null, mixed: false, empty: true, any: false, text: false, attrs: [], inclusions: [], exclusions: [] };
    expect(insertable(S, "proceduralStep", ["para"], 1, ["procedure", "mainProcedure"])).toContain("revst");
    expect(isValid(S, "proceduralStep", ["para", "revst"], ["procedure", "mainProcedure"])).toBe(true);
    S.elements.proceduralStep.exclusions = ["revst"];
    expect(insertable(S, "proceduralStep", ["para"], 1, ["procedure", "mainProcedure", "proceduralStep"])).not.toContain("revst");
  });
});


describe("content prompts", () => {
  it("marks the text slots of a new element and fills them", () => {
    const A: SchemaModel = { root: "acronym", kind: "xsd", elements: {
      acronym: { content: { k: "seq", min: 1, max: 1, items: [el("acronymTerm"), el("acronymDefinition")] }, mixed: false, empty: false, any: false, text: false, attrs: [], inclusions: [], exclusions: [] },
      acronymTerm: { content: null, mixed: false, empty: false, any: false, text: true, attrs: [], inclusions: [], exclusions: [] },
      acronymDefinition: { content: null, mixed: false, empty: false, any: false, text: true, attrs: [], inclusions: [], exclusions: [] },
    } };
    const t = template(A, "acronym", new Set(), 0, { texts: true });
    expect(t.texts!.map((x) => x.element)).toEqual(["acronymTerm", "acronymDefinition"]);
    const xml = fillTemplate(t.xml, { [t.texts![0].id]: "LPT", [t.texts![1].id]: "Low <pressure> turbine & co" });
    expect(xml).toBe("<acronym><acronymTerm>LPT</acronymTerm><acronymDefinition>Low &lt;pressure&gt; turbine &amp; co</acronymDefinition></acronym>");
    expect(template(A, "acronym", new Set()).xml).toBe("<acronym><acronymTerm></acronymTerm><acronymDefinition></acronymDefinition></acronym>");
  });
});
