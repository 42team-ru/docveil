import { useState, type CSSProperties } from "react";
import { Badge } from "@astryxdesign/core/Badge";
import {
  Layout,
  LayoutContent,
  LayoutHeader,
  LayoutPanel,
} from "@astryxdesign/core/Layout";
import { Tab, TabList } from "@astryxdesign/core/TabList";

import type {
  AskEnvelope,
  MaskingReport,
  PiiExtraction,
} from "../../../entity/pii/model/types";
import { ClarificationTab } from "./clarification-tab";
import { ContractSummaryTab } from "./contract-summary-tab";
import { PiiListTab } from "./pii-list-tab";
import { ProfilesTab } from "./profiles-tab";

const PANEL_WIDTH = 400;

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
  /** Весь отчёт прогона; `null` — документ показан без отчёта движка. */
  report: MaskingReport | null;
  /** Вопросы, на которых прогон встал; `null` — вопросов не было. */
  ask: AskEnvelope | null;
  /** Прогон, открытый на проверку: по нему уходят ответы человека. */
  runId: string | null;
  totalCount: number;
  notFoundIds: Set<string>;
};

/**
 * Правая панель экрана проверки: замены, профили сторон, вопросы агента и
 * карточка договора.
 */
export function ReviewPanel({
  extraction,
  report,
  ask,
  runId,
  totalCount,
  notFoundIds,
}: ReviewPanelProps) {
  const [selectedTab, setTab] = useState<string | null>(null);
  const questionCount = ask?.questions.filter((question) => question.kind !== "type").length ?? 0;
  const tab = selectedTab ?? (questionCount > 0 ? "ask" : "list");

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
                  endContent={
                    questionCount > 0 ? (
                      <Badge variant="warning" label={questionCount} />
                    ) : undefined
                  }
                />
                <Tab value="contract" label="Договор" />
              </TabList>
            </div>
          </LayoutHeader>
        }
        content={
          <LayoutContent padding={0} label="Содержимое вкладки">
            {tab === "list" ? (
              <PiiListTab extraction={extraction} notFoundIds={notFoundIds} />
            ) : null}
            {tab === "profiles" ? (
              <ProfilesTab
                profiles={report?.profiles ?? []}
                groups={report?.plan?.groups ?? []}
              />
            ) : null}
            {tab === "ask" ? <ClarificationTab ask={ask} runId={runId} /> : null}
            {tab === "contract" ? (
              <ContractSummaryTab summary={report?.contractSummary ?? null} />
            ) : null}
          </LayoutContent>
        }
      />
    </LayoutPanel>
  );
}
