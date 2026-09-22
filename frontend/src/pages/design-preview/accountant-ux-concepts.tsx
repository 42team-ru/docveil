import { useRef, useState } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronRight,
  FileCheck2,
  FileClock,
  FileSearch,
  Files,
  LayoutDashboard,
  Search,
  ShieldCheck,
  Upload,
} from "lucide-react";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { Icon } from "@astryxdesign/core/Icon";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Heading, Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";

import { ScreenLayout } from "../../shared/ui/screen-layout/screen-layout";
import "./accountant-ux-concepts.css";

type ConceptScreen = "overview" | "upload" | "documents" | "review" | "result";

const SCREENS: { id: ConceptScreen; label: string; icon: typeof Files }[] = [
  { id: "overview", label: "Рабочий стол", icon: LayoutDashboard },
  { id: "upload", label: "Новый документ", icon: Upload },
  { id: "documents", label: "Документы", icon: Files },
  { id: "review", label: "Проверка", icon: FileSearch },
  { id: "result", label: "Результат", icon: FileCheck2 },
];

const MOCK_DOCUMENTS = [
  {
    name: "Договор поставки оборудования № 45-09/26",
    counterparty: "ООО «Вектор-Снаб»",
    date: "23 сен 2026",
    status: "Нужна проверка",
    variant: "warning" as const,
  },
  {
    name: "Счёт на оплату № 118",
    counterparty: "АО «Городские системы»",
    date: "22 сен 2026",
    status: "Готов к скачиванию",
    variant: "success" as const,
  },
  {
    name: "Дополнительное соглашение № 2",
    counterparty: "ООО «Северный проект»",
    date: "22 сен 2026",
    status: "Обрабатывается",
    variant: "info" as const,
  },
  {
    name: "Акт оказанных услуг за август",
    counterparty: "ООО «Техсервис»",
    date: "19 сен 2026",
    status: "Проверка завершена",
    variant: "neutral" as const,
  },
];

function ConceptButton({
  screen,
  active,
  onSelect,
}: {
  screen: (typeof SCREENS)[number];
  active: boolean;
  onSelect: (screen: ConceptScreen) => void;
}) {
  return (
    <Button
      size="sm"
      variant={active ? "primary" : "secondary"}
      label={screen.label}
      icon={<Icon icon={screen.icon} size="sm" />}
      onClick={() => onSelect(screen.id)}
      aria-current={active ? "page" : undefined}
    />
  );
}

function SummaryCard({
  label,
  value,
  note,
  icon,
  tone,
}: {
  label: string;
  value: string;
  note: string;
  icon: typeof Files;
  tone: "blue" | "orange" | "green";
}) {
  return (
    <Card padding={4} className={`ux-summary-card ux-summary-card--${tone}`}>
      <HStack gap={3} vAlign="start">
        <span className="ux-summary-icon">
          <Icon icon={icon} size="md" />
        </span>
        <VStack gap={1}>
          <Text type="supporting" color="secondary">{label}</Text>
          <Heading level={2}>{value}</Heading>
          <Text type="supporting" color="secondary">{note}</Text>
        </VStack>
      </HStack>
    </Card>
  );
}

function OverviewScreen({
  openReview,
  openDocuments,
}: {
  openReview: () => void;
  openDocuments: () => void;
}) {
  return (
    <VStack gap={5}>
      <div className="ux-welcome-row">
        <div>
          <Heading level={2}>Здравствуйте, Елена</Heading>
          <Text type="supporting" color="secondary">
            Здесь документы, которым нужно ваше внимание.
          </Text>
        </div>
        <Badge variant="neutral" label="Среда, 23 сентября" />
      </div>

      <div className="ux-summary-grid">
        <SummaryCard
          label="Нужно проверить"
          value="3 документа"
          note="Можно продолжить с любого"
          icon={FileClock}
          tone="orange"
        />
        <SummaryCard
          label="Готово к скачиванию"
          value="4 документа"
          note="Обезличивание завершено"
          icon={ArrowDownToLine}
          tone="green"
        />
        <SummaryCard
          label="Обработано за неделю"
          value="18 документов"
          note="Ошибок при обработке нет"
          icon={ShieldCheck}
          tone="blue"
        />
      </div>

      <div className="ux-overview-grid">
        <Card padding={0} className="ux-panel-card">
          <div className="ux-panel-heading">
            <div>
              <Heading level={4}>Требуют проверки</Heading>
              <Text type="supporting" color="secondary">Сначала — то, что ждёт вашего решения</Text>
            </div>
            <Button
              size="sm"
              variant="ghost"
              label="Все документы"
              icon={<Icon icon={ArrowRight} size="sm" />}
              onClick={openDocuments}
            />
          </div>
          <div className="ux-task-list">
            {MOCK_DOCUMENTS.slice(0, 3).map((document, index) => (
              <button
                className="ux-task-row"
                key={document.name}
                onClick={openReview}
                type="button"
              >
                <span className="ux-task-index">{index + 1}</span>
                <span className="ux-task-main">
                  <strong>{document.name}</strong>
                  <span>{document.counterparty} · {document.date}</span>
                </span>
                <Badge variant={document.variant} label={document.status} />
                <Icon icon={ChevronRight} size="sm" />
              </button>
            ))}
          </div>
        </Card>

        <Card padding={4} className="ux-panel-card ux-activity-card">
          <Heading level={4}>Недавние действия</Heading>
          <VStack gap={3}>
            <ActivityItem time="10:42" title="Файл готов" detail="Счёт на оплату № 118" tone="green" />
            <ActivityItem time="10:18" title="Начата проверка" detail="Договор поставки № 45-09/26" tone="blue" />
            <ActivityItem time="Вчера" title="Документ скачан" detail="Акт оказанных услуг за август" tone="gray" />
          </VStack>
        </Card>
      </div>
    </VStack>
  );
}

function ActivityItem({
  time,
  title,
  detail,
  tone,
}: {
  time: string;
  title: string;
  detail: string;
  tone: "green" | "blue" | "gray";
}) {
  return (
    <div className="ux-activity-item">
      <span className={`ux-activity-dot ux-activity-dot--${tone}`} />
      <div>
        <Text type="label" weight="medium">{title}</Text>
        <Text type="supporting" color="secondary">{detail}</Text>
      </div>
      <span className="ux-activity-time">{time}</span>
    </div>
  );
}

function UploadScreen({ onStart }: { onStart: () => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState("Договор поставки № 45-09/26.docx");
  const [fileSize, setFileSize] = useState("2,4 МБ");
  const selectFile = (file: File) => {
    setFileName(file.name);
    setFileSize(`${(file.size / (1024 * 1024)).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} МБ`);
  };

  return (
    <VStack gap={4}>
      <div className="ux-page-heading">
        <div>
          <Heading level={2}>Новый документ</Heading>
          <Text type="supporting" color="secondary">Добавьте файл и выберите, что нужно скрыть.</Text>
        </div>
      </div>
      <div className="ux-upload-layout">
        <Card
          padding={5}
          className="ux-upload-dropzone"
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            const file = event.dataTransfer.files[0];
            if (file) selectFile(file);
          }}
        >
          <span className="ux-upload-icon"><Icon icon={Upload} size="lg" /></span>
          <Heading level={4}>Перетащите документы сюда</Heading>
          <Text type="supporting" color="secondary">или выберите файлы на компьютере</Text>
          <input
            ref={inputRef}
            className="ux-file-input"
            type="file"
            accept=".docx,.xlsx,.pdf"
            onChange={(event) => {
              const file = event.currentTarget.files?.[0];
              if (file) selectFile(file);
            }}
          />
          <Button variant="secondary" label="Выбрать файлы" onClick={() => inputRef.current?.click()} />
          <Text type="supporting" color="secondary" size="sm">DOCX, XLSX, PDF · до 50 МБ на файл</Text>
        </Card>
        <Card padding={4} className="ux-upload-options">
          <Heading level={4}>Что обезличить</Heading>
          <Text type="supporting" color="secondary">Обычно достаточно стандартного набора.</Text>
          {[
            ["Организации и ФИО", "Стороны, представители, подписанты"],
            ["Реквизиты", "ИНН, ОГРН, счета и контакты"],
            ["Адреса", "Адреса организаций и объектов"],
          ].map(([title, description]) => (
            <div className="ux-check-option" key={title}>
              <span className="ux-check-square"><Icon icon={Check} size="sm" /></span>
              <span><strong>{title}</strong><small>{description}</small></span>
            </div>
          ))}
          <div className="ux-upload-selected">
            <Icon icon={FileCheck2} size="md" />
            <div><Text type="label" weight="semibold">{fileName}</Text><Text type="supporting" color="secondary">{fileSize} · готов к обработке</Text></div>
            <Badge variant="success" label="Добавлен" />
          </div>
          <Button variant="primary" label="Начать обработку" icon={<Icon icon={ArrowRight} size="sm" />} onClick={onStart} />
        </Card>
      </div>
      <Card padding={3} className="ux-review-safety-note"><HStack gap={2} vAlign="center"><Icon icon={ShieldCheck} size="sm" /><Text type="supporting">Оригинал остаётся без изменений. Перед скачиванием вы сможете проверить результат.</Text></HStack></Card>
    </VStack>
  );
}

function DocumentsScreen({ openReview, openUpload }: { openReview: () => void; openUpload: () => void }) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("Все");
  const visibleDocuments = MOCK_DOCUMENTS.filter((document) => {
    const matchesQuery = `${document.name} ${document.counterparty}`.toLocaleLowerCase("ru").includes(query.toLocaleLowerCase("ru"));
    const matchesFilter = filter === "Все" || (filter === "Нужно проверить" ? document.variant === "warning" : filter === "Готово" ? document.variant === "success" : document.variant === "info");
    return matchesQuery && matchesFilter;
  });
  return (
    <VStack gap={4}>
      <div className="ux-page-heading">
        <div>
          <Heading level={2}>Документы</Heading>
          <Text type="supporting" color="secondary">
            Все файлы и понятный статус каждого.
          </Text>
        </div>
        <Button
          variant="primary"
          label="Добавить документы"
          icon={<Icon icon={Upload} size="sm" />}
          onClick={openUpload}
        />
      </div>

      <Card padding={4} className="ux-filter-card">
        <HStack gap={3} vAlign="center" wrap="wrap">
          <TextInput
            label="Поиск"
            isLabelHidden
            placeholder="Название или контрагент"
            startIcon={Search}
            width={340}
            value={query}
            onChange={setQuery}
          />
          <div className="ux-filter-chips" aria-label="Фильтр документов">
            {["Все", "Нужно проверить", "Готово", "В обработке"].map((item) => (
              <Button key={item} size="sm" variant={filter === item ? "primary" : "ghost"} label={item} onClick={() => setFilter(item)} />
            ))}
          </div>
        </HStack>
      </Card>

      <Card padding={0} className="ux-panel-card ux-table-card">
        <div className="ux-table-caption">
          <Text type="label" weight="semibold">Последние документы</Text>
          <Text type="supporting" color="secondary">Показано {visibleDocuments.length} из 18</Text>
        </div>
        <div className="ux-table-scroll">
          <table className="ux-table">
            <thead>
              <tr>
                <th>Документ</th>
                <th>Контрагент</th>
                <th>Добавлен</th>
                <th>Статус</th>
                <th aria-label="Действие" />
              </tr>
            </thead>
            <tbody>
              {visibleDocuments.map((document) => (
                <tr key={document.name} onClick={openReview}>
                  <td>
                    <span className="ux-doc-name">{document.name}</span>
                    <span className="ux-doc-format">DOCX · 2,4 МБ</span>
                  </td>
                  <td>{document.counterparty}</td>
                  <td>{document.date}</td>
                  <td><Badge variant={document.variant} label={document.status} /></td>
                  <td>
                    <Button
                      size="sm"
                      variant="ghost"
                      label={document.variant === "warning" ? "Продолжить" : "Открыть"}
                      onClick={(event) => {
                        event.stopPropagation();
                        openReview();
                      }}
                    />
                  </td>
                </tr>
              ))}
              {visibleDocuments.length === 0 ? <tr><td colSpan={5}>Документы не найдены</td></tr> : null}
            </tbody>
          </table>
        </div>
      </Card>
      <Text type="supporting" color="secondary" size="sm">
        Подсказка: завершённые файлы остаются в журнале — их можно найти поиском.
      </Text>
    </VStack>
  );
}

function ReviewScreen({ showResult, backToDocuments }: { showResult: () => void; backToDocuments: () => void }) {
  const [showAllFindings, setShowAllFindings] = useState(false);

  return (
    <VStack gap={4}>
      <div className="ux-review-topline">
        <div>
          <div className="ux-step-label"><span>Шаг 2 из 3</span><span>Проверка найденных данных</span></div>
          <Heading level={3}>Договор поставки № 45-09/26.docx</Heading>
          <Text type="supporting" color="secondary">ООО «Вектор-Снаб» · добавлен сегодня в 10:18</Text>
        </div>
        <div className="ux-review-actions">
          <Button size="sm" variant="secondary" label="Назад к документам" onClick={backToDocuments} />
          <Button
            variant="primary"
            label="Применить и продолжить"
            icon={<Icon icon={ArrowRight} size="sm" />}
            onClick={showResult}
          />
        </div>
      </div>

      <div className="ux-review-workspace">
        <Card padding={4} className="ux-preview-card">
          <div className="ux-preview-toolbar">
            <HStack gap={2} vAlign="center">
              <Badge variant="neutral" label="Предпросмотр" />
              <Text type="supporting" color="secondary">Страница 1 из 4</Text>
            </HStack>
            <Text type="supporting" color="secondary">Маски будет 8</Text>
          </div>
          <div className="ux-paper-wrap">
            <article className="ux-paper" aria-label="Предпросмотр договора">
              <div className="ux-paper-brand">ДОГОВОР ПОСТАВКИ № 45-09/26</div>
              <p className="ux-paper-small">г. Москва <span className="ux-highlight">«23» сентября 2026 г.</span></p>
              <p>
                <span className="ux-highlight">ООО «Вектор-Снаб»</span>, именуемое в дальнейшем
                «Поставщик», в лице <span className="ux-highlight">Иванова Ивана Ивановича</span>,
                действующего на основании Устава, с одной стороны, и Заказчик, с другой стороны,
                заключили настоящий договор о нижеследующем.
              </p>
              <h4>1. Предмет договора</h4>
              <p>
                Поставщик обязуется поставить оборудование по адресу: <span className="ux-highlight">г. Москва, ул. Примерная, д. 10</span>,
                а Заказчик обязуется принять и оплатить товар на условиях настоящего договора.
              </p>
              <h4>2. Стоимость и порядок расчётов</h4>
              <p>
                Цена договора составляет <span className="ux-highlight">1 250 000 рублей</span> и включает все расходы Поставщика.
              </p>
              <div className="ux-paper-signature">
                <span>ПОСТАВЩИК</span><span>ЗАКАЗЧИК</span>
              </div>
              <div className="ux-paper-lines"><i /><i /><i /><i /></div>
            </article>
          </div>
        </Card>

        <Card padding={0} className="ux-findings-card">
          <div className="ux-findings-header">
            <div>
              <Heading level={4}>Что будет скрыто</Heading>
              <Text type="supporting" color="secondary">8 фрагментов в 4 группах</Text>
            </div>
            <Badge variant="warning" label="2 требуют внимания" />
          </div>
          <div className="ux-findings-scroll">
            <FindingGroup
              title="Стороны и представители"
              rows={[
                { type: "Организация", sample: "ООО «Вектор-Снаб»", status: "Проверено" },
                { type: "ФИО", sample: "Иванов Иван Иванович", status: "Проверено" },
                { type: "Подписант", sample: "Должность и организация подписанта", status: "Проверьте" },
                ...(showAllFindings ? [{ type: "Телефон представителя", sample: "+7 (9••) •••-12-34", status: "Проверено" as const }] : []),
              ]}
            />
            <FindingGroup
              title="Реквизиты и контакты"
              rows={[
                { type: "ИНН", sample: "77•••••••42", status: "Проверено" },
                { type: "Адрес", sample: "г. Москва, ул. Примерная…", status: "Проверено" },
                { type: "Сумма договора", sample: "1 250 000 рублей", status: "Проверьте" },
                ...(showAllFindings ? [{ type: "Электронная почта", sample: "i••••v@vector.ru", status: "Проверено" as const }] : []),
              ]}
            />
          </div>
          <div className="ux-findings-footer">
            <Text type="supporting" color="secondary">
              Нажмите на фрагмент, чтобы увидеть его в документе.
            </Text>
            <Button
              size="sm"
              variant="ghost"
              label={showAllFindings ? "Свернуть список" : "Показать все 8"}
              icon={<Icon icon={ChevronRight} size="sm" />}
              onClick={() => setShowAllFindings((current) => !current)}
            />
          </div>
        </Card>
      </div>
      <Card padding={3} className="ux-review-safety-note">
        <HStack gap={2} vAlign="center">
          <Icon icon={ShieldCheck} size="sm" />
          <Text type="supporting">
            Исходный документ не меняется. Перед скачиванием можно проверить готовый файл.
          </Text>
        </HStack>
      </Card>
    </VStack>
  );
}

function FindingGroup({
  title,
  rows,
}: {
  title: string;
  rows: { type: string; sample: string; status: "Проверено" | "Проверьте" }[];
}) {
  return (
    <section className="ux-finding-group">
      <Heading level={6}>{title}</Heading>
      {rows.map((row) => (
        <div className="ux-finding-row" key={row.type}>
          <div>
            <Text type="label" weight="medium">{row.type}</Text>
            <Text type="supporting" color="secondary">{row.sample}</Text>
          </div>
          <Badge variant={row.status === "Проверено" ? "success" : "warning"} label={row.status} />
        </div>
      ))}
    </section>
  );
}

function ResultScreen({
  goDocuments,
  goReview,
}: {
  goDocuments: () => void;
  goReview: () => void;
}) {
  const [downloaded, setDownloaded] = useState(false);

  return (
    <VStack gap={5}>
      <Card padding={5} className="ux-result-hero">
        <span className="ux-result-check"><Icon icon={Check} size="lg" /></span>
        <Heading level={2}>Документ готов</Heading>
        <Text type="supporting" color="secondary">
          Проверка завершена. Исходный файл сохранён отдельно.
        </Text>
        <div className="ux-result-file">
          <Icon icon={FileCheck2} size="md" />
          <div>
            <Text type="label" weight="semibold">Договор поставки № 45-09/26.docx</Text>
            <Text type="supporting" color="secondary">DOCX · готов к скачиванию · 2,4 МБ</Text>
          </div>
          <StackItem size="fill" />
          <Button
            variant="primary"
            label={downloaded ? "Файл скачан" : "Скачать документ"}
            icon={<Icon icon={downloaded ? CheckCircle2 : ArrowDownToLine} size="sm" />}
            onClick={() => setDownloaded(true)}
          />
        </div>
      </Card>

      <div className="ux-result-grid">
        <Card padding={4} className="ux-panel-card">
          <Heading level={4}>Что изменилось</Heading>
          <div className="ux-result-stats">
            <div><strong>8</strong><span>фрагментов скрыто</span></div>
            <div><strong>4</strong><span>группы данных</span></div>
            <div><strong>0</strong><span>ошибок структуры</span></div>
          </div>
          <div className="ux-result-note">
            <Icon icon={ShieldCheck} size="sm" />
            <Text type="supporting">Таблицы и разметка документа сохранены.</Text>
          </div>
        </Card>
        <Card padding={4} className="ux-panel-card">
          <Heading level={4}>Дальше</Heading>
          <VStack gap={2}>
            <Button
              variant="secondary"
              label="Посмотреть список замен"
              icon={<Icon icon={FileSearch} size="sm" />}
              onClick={goReview}
            />
            <Button
              variant="ghost"
              label="Вернуться к документам"
              icon={<Icon icon={Files} size="sm" />}
              onClick={goDocuments}
            />
          </VStack>
        </Card>
      </div>
    </VStack>
  );
}

export function AccountantUxConceptsPage() {
  const [screen, setScreen] = useState<ConceptScreen>("overview");
  const activeScreen = SCREENS.find((item) => item.id === screen) ?? SCREENS[0]!;

  return (
    <ScreenLayout
      title={activeScreen.label}
      meta={<Badge variant="info" label="Концепт · не рабочая функция" />}
      contentPadding={4}
    >
      <div className="ux-concept-page">
        <div className="ux-concept-nav" role="tablist" aria-label="Экраны концепта">
          {SCREENS.map((item) => (
            <ConceptButton
              key={item.id}
              screen={item}
              active={screen === item.id}
              onSelect={setScreen}
            />
          ))}
        </div>
        <div className="ux-concept-stage" key={screen}>
          {screen === "overview" ? (
            <OverviewScreen
              openReview={() => setScreen("review")}
              openDocuments={() => setScreen("documents")}
            />
          ) : null}
          {screen === "documents" ? (
            <DocumentsScreen openReview={() => setScreen("review")} openUpload={() => setScreen("upload")} />
          ) : null}
          {screen === "upload" ? (
            <UploadScreen onStart={() => setScreen("review")} />
          ) : null}
          {screen === "review" ? (
            <ReviewScreen showResult={() => setScreen("result")} backToDocuments={() => setScreen("documents")} />
          ) : null}
          {screen === "result" ? (
            <ResultScreen
              goDocuments={() => setScreen("documents")}
              goReview={() => setScreen("review")}
            />
          ) : null}
        </div>
        <div className="ux-concept-disclaimer">
          <Text type="supporting" color="secondary" size="sm">
            Демонстрационный макет · данные вымышлены · кнопки показывают переходы между экранами
          </Text>
          <a href="https://edo.1c.ru/handbook/rabota-s-elektronnymi-dokumentami/interfeysy-1s-edo-legkiy-i-rasshirennyy/" target="_blank" rel="noreferrer">
            На чём основаны решения
          </a>
        </div>
      </div>
    </ScreenLayout>
  );
}
