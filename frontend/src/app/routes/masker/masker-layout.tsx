import { FilePlus2, FileText, PanelsTopLeft, ShieldCheck } from "lucide-react";
import { Outlet, useLocation } from "react-router";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";

import { isAdmin } from "../../../entity/user/model/roles";
import { useAuthSession } from "../../../shared/model/use-auth-session";
import { AccountTrigger } from "../../../features/account/ui/account-trigger";
import { useAccount } from "../../../features/account/api/use-account";
import {
  PanelShell,
  type PanelNavGroup,
} from "../../../shared/ui/panel-shell/panel-shell";

/**
 * Каркас панели обезличивания: верхнее меню + область экрана.
 * Роут-модуль знает только состав меню, всю верстку держит `PanelShell`.
 *
 * В меню одна вкладка — «Документы»: вход в проверку и отчёт идёт только
 * через журнал, отдельных пунктов для них больше нет. Вторая группа —
 * «Администрирование» — появляется только у роли `admin` (`entity/user/model/roles`);
 * настоящая защита самого раздела — на бэкенде, здесь только видимость пункта меню.
 */
export default function MaskerLayout() {
  const { pathname } = useLocation();
  // Все экраны под этим каркасом ходят в закрытый API: без действующей сессии
  // показывать их незачем — хук уводит на вход.
  useAuthSession();
  const { data: account } = useAccount();

  const groups: PanelNavGroup[] = [
    {
      title: "Работа",
      items: [{ to: "/documents", label: "Документы", icon: FileText }],
    },
    ...(import.meta.env.DEV
      ? [{ title: "Макеты", items: [{ to: "/design-preview", label: "Концепт UI", icon: PanelsTopLeft }] }]
      : []),
    ...(isAdmin(account)
      ? [
          {
            title: "Администрирование",
            items: [{ to: "/admin", label: "Админка", icon: ShieldCheck }],
          },
        ]
      : []),
  ];

  return (
    <PanelShell
      heading="DocVeil"
      headingIcon={
        <img
          src="/logo.png"
          alt="DocVeil"
          className="size-full object-contain"
        />
      }
      groups={groups}
      currentPath={pathname}
      navStartContent={
        <Button
          size="sm"
          variant="primary"
          label="Новый документ"
          icon={<Icon icon={FilePlus2} size="sm" />}
          href="/"
        />
      }
      accountTrigger={<AccountTrigger />}
    >
      <Outlet />
    </PanelShell>
  );
}
