import { forwardRef } from "react";
import { Link } from "react-router";

type RouterLinkProps = Omit<React.ComponentPropsWithoutRef<"a">, "href"> & {
  href?: string;
  viewTransition?: boolean;
};

/**
 * Адаптер между Astryx и react-router: компоненты дизайн-системы отдают ссылке
 * `href`, а `<Link>` роутера ждёт `to`. Подставляется через `LinkProvider`,
 * чтобы вся навигация шла клиентским переходом, без перезагрузки страницы.
 */
export const RouterLink = forwardRef<HTMLAnchorElement, RouterLinkProps>(
  function RouterLink({ href = "", viewTransition = true, ...rest }, ref) {
    return <Link {...rest} ref={ref} to={href} viewTransition={viewTransition} />;
  },
);
