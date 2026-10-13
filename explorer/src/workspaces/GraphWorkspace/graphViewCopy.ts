import type { FocusedUnavailableReason, GroupedViewUnavailableReason } from "./types";

const GROUPED_VIEW_COPY = {
  "communities-undetected": "检测到社区之前无法使用分组视图。",
  "community-nodes-missing": "无法生成社区节点，分组视图不可用。",
} as const;

const FOCUSED_MODE_COPY = {
  "no-selection": "选择一个节点，在聚焦模式中查看。",
  "grouped-unresolvable": "这个分组选择无法使用聚焦模式。",
  "not-in-graph": "所选项不在当前图谱中。",
} as const;

export function groupedViewReasonText(
  reason: GroupedViewUnavailableReason | null | undefined,
): string | null {
  if (!reason) {
    return null;
  }

  switch (reason.code) {
    case "communities-undetected":
      return GROUPED_VIEW_COPY["communities-undetected"];
    case "community-nodes-missing":
      return GROUPED_VIEW_COPY["community-nodes-missing"];
    case "invalid-community-layout":
      return `分组节点 ${reason.nodeId} 的坐标无效。`;
    case "missing-grouped-node":
      return `分组边 ${reason.edgeId} 引用了不存在的分组节点。`;
  }
}

export function focusedUnavailableReasonText(
  reason: FocusedUnavailableReason | null | undefined,
): string | null {
  if (!reason) {
    return null;
  }

  return FOCUSED_MODE_COPY[reason.code];
}
