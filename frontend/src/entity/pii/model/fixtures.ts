import questionsPayload from "./questions.fixture.json";
import reportPayload from "./report.fixture.json";
import { parseAskEnvelope, parseMaskingReport } from "./schema";

/**
 * Настоящая выдача движка, а не выдумка: `report.fixture.json` и
 * `questions.fixture.json` — это дословные копии артефактов прогона по
 * `backend/fixtures/labeled/contract_08_roles.docx`.
 *
 * ```
 * cd backend
 * .venv/Scripts/python -m masker.cli fixtures/labeled/contract_08_roles.docx \
 *   --out out/fe-fixtures --profile --redact-style marker --html
 * .venv/Scripts/python -m masker.cli fixtures/labeled/contract_08_roles.docx \
 *   --out out/fe-ask --profile --redact-style marker --ask
 * ```
 *
 * Файлы лежат рядом целиком и не переписываются руками: как только форма
 * `report.json` поедет, `parseMaskingReport` упадёт на настоящих данных, а не
 * на подогнанной под парсер копии. Раньше здесь был обрезанный до
 * `chunk_count` + `chunks` литерал, и всё остальное экраны досочиняли своими
 * фикстурами — цифры в панели и в отчёте расходились.
 *
 * Почему именно этот документ: он единственный из размеченных даёт сразу и
 * `locator: ["body", N]`, и `locator: ["table", t, r, c, p]` (chunk-004), и
 * роли сторон открытым словарём — «Заказчик»/«Исполнитель», а не зашитые
 * «поставщик»/«покупатель». Маркер несёт роль: `[ЗАКАЗЧИК-ОРГАНИЗАЦИЯ]`.
 *
 * Документ рядом — `public/contract-roles.docx`, это `masked_highlight.docx`
 * того же прогона: маркеры уже вписаны в файл, исходных ПДн в нём нет.
 */
export const maskingReportFixture = parseMaskingReport(reportPayload);

/** Чанки того же отчёта — то, с чем работают вьюер и панель проверки. */
export const piiExtractionFixture = maskingReportFixture.extraction;

/**
 * Конверт паузы графа. В `report.json` вопросов нет вовсе: прогон, который
 * дошёл до отчёта, на человеке уже не стоит. Поэтому вопросы — отдельный
 * артефакт того же документа, снятый прогоном с `--ask`.
 *
 * Обратите внимание на `TYPE-inn` и `TYPE-bank_account`: у них единственный
 * вариант ответа — «маскировать». Так выглядит двойное подтверждение со
 * стороны движка, когда прогон запущен без `--unmask-critical`.
 */
export const askEnvelopeFixture = parseAskEnvelope(questionsPayload);

/** Файл, открытый на проверку — путь в /public для fetch на клиенте. */
export const reviewedDocumentFixture = {
  name: maskingReportFixture.input,
  format: maskingReportFixture.format,
  fileUrl: "/contract-roles.docx",
};
