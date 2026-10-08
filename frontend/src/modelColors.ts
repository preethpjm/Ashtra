/** Colours of the 3D item ↔ BOM status (shared by the viewer and the lists; no three.js import here). */
export const STATUS_COLOR: Record<string, string> = {
  matched: "#2f8f5b", linked: "#3a6ea5", fuzzy: "#d9a400", quantity: "#e07b26", unmatched: "#c0392b",
};
export const STATUS_LABEL: Record<string, string> = {
  matched: "Matched to the BOM", linked: "Part number in the library", fuzzy: "Matched with doubt",
  quantity: "Quantity differs", unmatched: "Not in the BOM",
};
