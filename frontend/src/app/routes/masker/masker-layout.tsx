import {
  FileCheck2,
  FilePlus2,
  History,
  ListChecks,
  ShieldCheck,
} from "lucide-react";
import { Outlet, useLocation } from "react-router";
import { Icon } from "@astryxdesign/core/Icon";

import { usePendingGroupCount } from "../../../entity/pii/model/selectors";
import { useAuthSession } from "../../../shared/model/use-auth-session";
import { ProcessMonitor } from "../../../features/document-processing/ui/process-monitor";
import {
  PanelShell,
  type PanelNavGroup,
} from "../../../shared/ui/panel-shell/panel-shell";

/**
 * Каркас панели обезличивания: верхнее меню + область экрана.
 * Роут-модуль знает только состав меню, всю верстку держит `PanelShell`.
 */
export default function MaskerLayout() {
  const { pathname } = useLocation();
  const pendingCount = usePendingGroupCount();
  // Все экраны под этим каркасом ходят в закрытый API: без действующей сессии
  // показывать их незачем — хук уводит на вход.
  useAuthSession();

  const groups: PanelNavGroup[] = [
    {
      title: "Работа",
      items: [
        { to: "/", label: "Новая задача", icon: FilePlus2 },
        { to: "/history", label: "История файлов", icon: History },
      ],
    },
    {
      title: "Текущая задача",
      items: [
        {
          to: "/review",
          label: "Проверка",
          icon: ListChecks,
          badge: pendingCount,
        },
        { to: "/report", label: "Отчёт", icon: FileCheck2 },
      ],
    },
  ];

  return (
    <PanelShell
      heading="TriemaMasker"
      headingIcon={<Icon icon={ShieldCheck} />}
      groups={groups}
      currentPath={pathname}
      navEndContent={<ProcessMonitor />}
    >
      <Outlet />
    </PanelShell>
  );
}
