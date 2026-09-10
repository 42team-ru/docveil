import { UploadPage } from "../../../pages/masker/upload-page";

export function meta() {
  return [{ title: "Новый документ · Обезличивание" }];
}

export default function UploadRoute() {
  return <UploadPage />;
}
