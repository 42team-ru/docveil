import { DocumentsPage } from "../../../pages/masker/documents-page";

export function meta() {
  return [{ title: "Документы · Обезличивание" }];
}

export default function DocumentsRoute() {
  return <DocumentsPage />;
}
