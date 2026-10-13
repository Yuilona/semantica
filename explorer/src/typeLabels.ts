// Display names for graph node/edge type keys. The backend relies on these
// English keys (e.g. "decision" lists decisions, CAUSED/INFLUENCED drive causal
// tracing, "involves" recovers decision entities), so data keeps them and only
// the UI shows the Chinese name. Unknown types are shown as-is.
const TYPE_LABELS: Record<string, string> = {
  decision: "决策",
  involves: "涉及",
  CAUSED: "导致",
  INFLUENCED: "影响",
  PRECEDENT_FOR: "作为先例",
  category: "类别",
  decision_maker: "决策者",
  entity: "实体",
  belongs_to: "属于",
  made_by: "决策者为",
  // W3C PROV-O classes (lineage view)
  Entity: "实体",
  Activity: "活动",
  Agent: "执行者",
  wasDerivedFrom: "派生自",
};

export function typeLabel(type: string | null | undefined): string {
  if (!type) return "";
  return TYPE_LABELS[type] ?? type;
}
