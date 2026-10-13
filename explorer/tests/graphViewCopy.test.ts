import assert from "node:assert/strict";
import test from "node:test";

import {
  focusedUnavailableReasonText,
  groupedViewReasonText,
} from "../src/workspaces/GraphWorkspace/graphViewCopy.ts";

test("groupedViewReasonText owns grouped-view copy for every reason code", () => {
  assert.equal(
    groupedViewReasonText({ code: "communities-undetected" }),
    "检测到社区之前无法使用分组视图。",
  );
  assert.equal(
    groupedViewReasonText({ code: "community-nodes-missing" }),
    "无法生成社区节点，分组视图不可用。",
  );
  assert.equal(
    groupedViewReasonText({ code: "invalid-community-layout", nodeId: "community-a" }),
    "分组节点 community-a 的坐标无效。",
  );
  assert.equal(
    groupedViewReasonText({ code: "missing-grouped-node", edgeId: "edge-1" }),
    "分组边 edge-1 引用了不存在的分组节点。",
  );
  assert.equal(groupedViewReasonText(null), null);
});

test("focusedUnavailableReasonText owns focused-mode copy for every reason code", () => {
  assert.equal(
    focusedUnavailableReasonText({ code: "no-selection" }),
    "选择一个节点，在聚焦模式中查看。",
  );
  assert.equal(
    focusedUnavailableReasonText({ code: "grouped-unresolvable" }),
    "这个分组选择无法使用聚焦模式。",
  );
  assert.equal(
    focusedUnavailableReasonText({ code: "not-in-graph" }),
    "所选项不在当前图谱中。",
  );
  assert.equal(focusedUnavailableReasonText(null), null);
});
