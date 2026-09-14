import { useSearchParams } from "react-router";
import { BarChart3, FileClock, Users } from "lucide-react";
import { Icon } from "@astryxdesign/core/Icon";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { Text } from "@astryxdesign/core/Text";

import { ScreenLayout } from "../../shared/ui/screen-layout/screen-layout";
import { AdminOverviewView } from "./admin-overview-view";
import { AdminUsersView } from "./admin-users-view";
import { AdminRunsView } from "./admin-runs-view";

type AdminTab = "overview" | "users" | "runs";

const CONTENT_PANEL_ID = "admin-tab-panel";

function parseTab(value: string | null): AdminTab {
  return value === "users" || value === "runs" ? value : "overview";
}

/**
 * Раздел администратора: сводка по системе целиком, все пользователи, все
 * прогоны — в отличие от остального продукта, который всегда работает в
 * рамках одного аккаунта. Доступность самой страницы решает роут-guard
 * (`app/routes/masker/admin.tsx`); здесь — только содержимое.
 */
export function AdminPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = parseTab(searchParams.get("tab"));

  return (
    <ScreenLayout
      title="Администрирование"
      meta={
        <Text type="supporting" color="secondary" size="sm">
          Видно только роли «Администратор»
        </Text>
      }
      tabs={
        <TabList
          value={tab}
          onChange={(value) =>
            setSearchParams(
              (params) => {
                const next = new URLSearchParams(params);
                if (value === "overview") next.delete("tab");
                else next.set("tab", value);
                return next;
              },
              { replace: true },
            )
          }
          role="tablist"
          size="sm"
        >
          <Tab
            value="overview"
            label="Обзор"
            icon={<Icon icon={BarChart3} size="sm" />}
            panelId={CONTENT_PANEL_ID}
          />
          <Tab
            value="users"
            label="Пользователи"
            icon={<Icon icon={Users} size="sm" />}
            panelId={CONTENT_PANEL_ID}
          />
          <Tab
            value="runs"
            label="Прогоны"
            icon={<Icon icon={FileClock} size="sm" />}
            panelId={CONTENT_PANEL_ID}
          />
        </TabList>
      }
      contentId={CONTENT_PANEL_ID}
    >
      {tab === "overview" ? <AdminOverviewView /> : null}
      {tab === "users" ? <AdminUsersView /> : null}
      {tab === "runs" ? <AdminRunsView /> : null}
    </ScreenLayout>
  );
}
