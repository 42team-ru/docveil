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
    route("dashboard", "routes/masker/dashboard.tsx"),
    route("documents", "routes/masker/documents.tsx"),
    route("documents/:runId", "routes/masker/document.tsx"),
    route("admin", "routes/masker/admin.tsx"),
  ]),
] satisfies RouteConfig;
