import { useState } from "react";
import { ScrollText, Users, Workflow } from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Icon } from "@astryxdesign/core/Icon";
import { Layout, LayoutContent, LayoutHeader } from "@astryxdesign/core/Layout";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { StatusDot } from "@astryxdesign/core/StatusDot";
import { Tab, TabList } from "@astryxdesign/core/TabList";

import { AgentPipeline } from "./agent-pipeline";
import { CallTraceLog } from "./call-trace-log";
import { PartyRolesPanel } from "./party-roles-panel";

type ProcessTab = "steps" | "roles" | "traces";

/**
 * Наблюдение за обработкой документа: компактная кнопка в шапке
 * (рядом с меню профиля) открывает обычное — не полноэкранное — диалоговое
 * окно с этапами, ролями и журналом вызовов.
 */
export function ProcessMonitor() {
  const [isOpen, setIsOpen] = useState(false);
  const [tab, setTab] = useState<ProcessTab>("steps");

  return (
    <>
      <Button
        size="sm"
        variant="secondary"
        icon={<Icon icon={ScrollText} size="sm" />}
        label="Обработка документа"
        onClick={() => setIsOpen(true)}
      />
      <Dialog isOpen={isOpen} onOpenChange={setIsOpen} width={720}>
        <Layout
          height="fill"
          header={
            <DialogHeader
              title="Обработка документа"
              subtitle="Конвейер агентов, роли сторон и журнал вызовов"
              onOpenChange={setIsOpen}
              endContent={
                <StatusDot variant="accent" label="Идёт обработка" isPulsing />
              }
            />
          }
          content={
            <LayoutContent
              padding={0}
              isScrollable={false}
              label="Обработка документа"
            >
              <Layout
                height="fill"
                header={
                  <LayoutHeader hasDivider>
                    <HStack vAlign="end" width="100%" height="100%">
                      <TabList
                        value={tab}
                        onChange={(value) => setTab(value as ProcessTab)}
                        size="sm"
                        layout="fill"
                      >
                        <Tab
                          value="steps"
                          label="Этапы"
                          icon={<Icon icon={Workflow} size="sm" />}
                        />
                        <Tab
                          value="roles"
                          label="Роли"
                          icon={<Icon icon={Users} size="sm" />}
                        />
                        <Tab
                          value="traces"
                          label="Трейсы"
                          icon={<Icon icon={ScrollText} size="sm" />}
                        />
                      </TabList>
                    </HStack>
                  </LayoutHeader>
                }
                content={
                  <LayoutContent isScrollable label="Содержимое вкладки">
                    {tab === "steps" ? <AgentPipeline /> : null}
                    {tab === "roles" ? <PartyRolesPanel /> : null}
                    {tab === "traces" ? (
                      <VStack gap={0} padding={4}>
                        <CallTraceLog />
                      </VStack>
                    ) : null}
                  </LayoutContent>
                }
              />
            </LayoutContent>
          }
        />
      </Dialog>
    </>
  );
}
