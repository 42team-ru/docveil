import { useSearchParams } from "react-router";

import {
  askEnvelopeFixture,
  maskingReportFixture,
  reviewedDocumentFixture,
} from "../../../entity/pii/model/fixtures";
import type {
  AskEnvelope,
  MaskingReport,
  PiiDocFormat,
  PiiExtraction,
} from "../../../entity/pii/model/types";
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
  /**
   * Весь `report.json` прогона. `null` — когда отчёта нет: так, xlsx-фикстура
   * состоит из одних чанков, потому что движок xlsx пока не обрабатывает
   * вовсе. Экраны обязаны уметь показать документ без отчёта, а не падать.
   */
  report: MaskingReport | null;
  /**
   * Конверт паузы графа, если прогон остановился на вопросах к человеку.
   * `null` — вопросов не было либо на них уже ответили.
   */
  ask: AskEnvelope | null;
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
      report: null,
      ask: null,
    };
  }

  return {
    extraction: maskingReportFixture.extraction,
    document: reviewedDocumentFixture,
    report: maskingReportFixture,
    ask: askEnvelopeFixture,
  };
}
