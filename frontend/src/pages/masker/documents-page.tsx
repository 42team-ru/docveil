import { useNavigate } from "react-router";
import { Plus } from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { VStack } from "@astryxdesign/core/Stack";

import { HistoryFilters } from "../../features/document-history/ui/history-filters";
import { HistoryTable } from "../../features/document-history/ui/history-table";
import { ScreenLayout } from "../../shared/ui/screen-layout/screen-layout";

/**
 * Журнал обработанных документов — единственная точка входа в проверку и
 * отчёт. Заголовок экрана не нужен: строка фильтров сама несёт заголовок
 * журнала по смыслу, а «Новая задача» стоит рядом с поиском.
 */
export function DocumentsPage() {
  const navigate = useNavigate();

  return (
    <ScreenLayout>
      <VStack gap={4}>
        <HistoryFilters
          actions={
            <Button
              size="lg"
              variant="primary"
              label="Новый документ"
              icon={<Icon icon={Plus} size="sm" />}
              onClick={() => navigate("/")}
            />
          }
        />
        <HistoryTable />
      </VStack>
    </ScreenLayout>
  );
}
