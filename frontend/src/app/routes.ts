import {
  type RouteConfig,
  index,
  layout,
  route,
} from "@react-router/dev/routes";

export default [
  route("login", "routes/auth/login.tsx"),
  layout("routes/masker/masker-layout.tsx", [
    index("routes/masker/upload.tsx"),
    route("review", "routes/masker/review.tsx"),
    route("report", "routes/masker/report.tsx"),
    route("history", "routes/masker/history.tsx"),
  ]),
] satisfies RouteConfig;
