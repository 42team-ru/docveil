import { useState } from "react";
import { Avatar } from "@astryxdesign/core/Avatar";

import { useAccount, useAvatarUrl } from "../api/use-account";
import { AccountDialog } from "./account-dialog";

/** Аватар в шапке: клик открывает `AccountDialog` напрямую — раньше здесь
 * висел `ProfilePopover` с заглушкой вместо реального имени пользователя. */
export function AccountTrigger() {
  const [isOpen, setIsOpen] = useState(false);
  const { data: user } = useAccount();
  const avatarUrl = useAvatarUrl(user?.has_avatar ?? false);

  return (
    <>
      <Avatar
        name={user?.full_name ?? "Пользователь"}
        src={avatarUrl}
        size="md"
        tooltip={false}
        onClick={() => setIsOpen(true)}
      />
      <AccountDialog isOpen={isOpen} onOpenChange={setIsOpen} />
    </>
  );
}
