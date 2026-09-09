import { useNavigate } from "react-router";
import { Plus } from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { HStack, VStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";

import { HistoryFilters } from "../../features/document-history/ui/history-filters";
import { HistoryTable } from "../../features/document-history/ui/history-table";
import { ScreenLayout } from "../../shared/ui/screen-layout/screen-layout";

/** Локальный архив обработанных документов. */
export function HistoryPage() {
  const navigate = useNavigate();

  return (
    <ScreenLayout
      title="История файлов"
      actions={
        <HStack gap={2}>
          <Button
            size="sm"
            variant="primary"
            label="Новая задача"
            icon={<Icon icon={Plus} size="sm" />}
            onClick={() => navigate("/")}
          />
        </HStack>
      }
    >
      <VStack gap={4}>
        <HistoryFilters />
        <HistoryTable />
      </VStack>
    </ScreenLayout>
  );
}
