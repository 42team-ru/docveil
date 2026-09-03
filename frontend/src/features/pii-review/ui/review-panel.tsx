import { useState, type CSSProperties } from "react";
import { Badge } from "@astryxdesign/core/Badge";
import {
  Layout,
  LayoutContent,
  LayoutHeader,
  LayoutPanel,
} from "@astryxdesign/core/Layout";
import { Tab, TabList } from "@astryxdesign/core/TabList";

import type { PiiExtraction } from "../../../entity/pii/model/types";
import { ClarificationTab } from "./clarification-tab";
import { PiiListTab } from "./pii-list-tab";
import { ProfilesTab } from "./profiles-tab";

const PANEL_WIDTH = 400;
const CLARIFICATION_COUNT = 2;

/**
 * LayoutHeader содержит внутренний паддинг, поэтому для выравнивания табов по
 * нижнему краю используем flex-end через отдельный wrapper (перенесено без
 * изменений из старого mask-review/ui/review-panel.tsx).
 */
const tabWrapperStyle: CSSProperties = {
  display: "flex",
  alignItems: "flex-end",
  paddingTop: 12,
  width: "100%",
};

type ReviewPanelProps = {
  extraction: PiiExtraction;
  totalCount: number;
  notFoundIds: Set<string>;
};

/** Правая панель экрана проверки: замены, профили сторон и уточнения агента. */
export function ReviewPanel({ extraction, totalCount, notFoundIds }: ReviewPanelProps) {
  const [tab, setTab] = useState("list");

  return (
    <LayoutPanel
      width={PANEL_WIDTH}
      hasDivider
      padding={0}
      isScrollable={false}
      label="Проверка замен"
    >
      <Layout
        height="fill"
        header={
          <LayoutHeader>
            <div style={tabWrapperStyle}>
              <TabList value={tab} onChange={setTab} size="sm" layout="fill" hasDivider>
                <Tab
                  value="list"
                  label="Замены"
                  endContent={<Badge variant="neutral" label={totalCount} />}
                />
                <Tab value="profiles" label="Профили" />
                <Tab
                  value="ask"
                  label="Вопросы"
                  endContent={<Badge variant="warning" label={CLARIFICATION_COUNT} />}
                />
              </TabList>
            </div>
          </LayoutHeader>
        }
        content={
          <LayoutContent padding={0} label="Содержимое вкладки">
            {tab === "list" ? (
              <PiiListTab extraction={extraction} notFoundIds={notFoundIds} />
            ) : null}
            {tab === "profiles" ? <ProfilesTab /> : null}
            {tab === "ask" ? <ClarificationTab /> : null}
          </LayoutContent>
        }
      />
    </LayoutPanel>
  );
}
