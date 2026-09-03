import { useSearchParams } from "react-router";

import {
  piiExtractionFixture,
  reviewedDocumentFixture,
} from "../../../entity/pii/model/fixtures";
import type { PiiDocFormat, PiiExtraction } from "../../../entity/pii/model/types";
import {
  piiExtractionXlsxFixture,
  reviewedXlsxDocumentFixture,
} from "../../../entity/pii/model/xlsx-fixtures";

export type ReviewedDocument = {
  name: string;
  format: PiiDocFormat;
  fileUrl: string;
};

export type ReviewData = {
  extraction: PiiExtraction;
  document: ReviewedDocument;
};

/**
 * Единственная точка входа за данными экрана `/review`. Сейчас отдаёт
 * фикстуры синхронно; когда появится сгенерированный Orval-клиент
 * (`src/shared/api/generated`), сюда встанет react-query хук с тем же
 * возвращаемым типом — вызывающий код (страница, панель, вьюер) менять не
 * придётся.
 *
 * В реальном продукте один документ на сессию проверки приходит с бэкенда —
 * выбора формата тут не будет вовсе. Пока это фикстуры, `?doc=xlsx`
 * переключает на реестр-таблицу, чтобы можно было проверить xlsx-вьюер без
 * отдельного экрана; по умолчанию — docx-контракт, как и раньше.
 */
export function useReviewData(): ReviewData {
  const [searchParams] = useSearchParams();

  if (searchParams.get("doc") === "xlsx") {
    return {
      extraction: piiExtractionXlsxFixture,
      document: reviewedXlsxDocumentFixture,
    };
  }

  return {
    extraction: piiExtractionFixture,
    document: reviewedDocumentFixture,
  };
}
