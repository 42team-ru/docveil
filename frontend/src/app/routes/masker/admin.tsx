import { Navigate } from "react-router";
import { Center } from "@astryxdesign/core/Center";
import { Spinner } from "@astryxdesign/core/Spinner";

import { isAdmin } from "../../../entity/user/model/roles";
import { useAccount } from "../../../features/account/api/use-account";
import { AdminPage } from "../../../pages/admin/admin-page";

export function meta() {
  return [{ title: "Админка · Обезличивание" }];
}

/**
 * Клиентский guard — только UX (не мигать чужим экраном, не пускать явку по
 * прямой ссылке раньше, чем прогрузится сессия). Настоящая защита —
 * `require_admin` на бэкенде (`backend/src/api/core/deps.py`): каждый запрос
 * `features/admin-overview/api/admin.ts` всё равно получит честный 403 без
 * роли `admin`, эта проверка его не подменяет.
 */
export default function AdminRoute() {
  const { data: account, isPending } = useAccount();

  if (isPending) {
    return (
      <Center>
        <Spinner label="Загрузка…" />
      </Center>
    );
  }

  if (!isAdmin(account)) {
    return <Navigate to="/documents" replace />;
  }

  return <AdminPage />;
}
