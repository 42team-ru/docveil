# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Internal legal and compliance staff at a single organization — lawyers, contract managers, and compliance officers — who process their own organization's documents daily. They work at a desktop workstation, operate under regulatory pressure (152-FZ), and handle batches of legal documents (contracts, agreements, acts) that contain personal data that must be removed before disclosure, archiving, or transfer.

## Product Purpose

TriemaMasker is a document de-identification (обезличивание) tool. It takes legal documents (PDF, DOCX, XLSX), runs a multi-agent AI pipeline to detect and replace personal data fragments with structured markers, lets the operator review and confirm each replacement with full visibility into AI confidence, and produces a clean masked output plus an audit report. Success means the operator can hand off a legally compliant, structurally intact document in a single focused session.

## Positioning

TriemaMasker combines a reviewable multi-agent pipeline (per data-type agents, per-fragment confidence scores, OCR fallback for scanned pages), structural document fidelity (tables, formatting, and layout survive masking), and built-in alignment to Russian personal-data categories and 152-FZ requirements — a combination a generic AI redaction tool or manual process cannot truthfully replicate.

## Operating Context

- **Batch upload:** one session typically covers multiple files; users stage and configure before committing.
- **Rule presets:** masking scope is governed by named rule profiles selecting which data types (ИНН, ФИО, addresses, party roles, custom types) to target and which marker style to apply (structured marker or full redaction block).
- **Processing pipeline:** AI agents run in sequence; operator observes live progress, agent traces, and party-role extraction in real time.
- **Manual review:** every detected fragment is surfaced with its original text, proposed marker, confidence score, page location, and contract side (supplier/buyer); the operator confirms, skips, or overrides each one.
- **Outputs:** masked document (PDF download), CSV/XLSX export, and a PDF audit report of all replacements.
- **History:** all processed documents are logged locally with run metadata, replacement counts, and version tracking for re-runs.
- **Model settings:** the AI layer is provider-agnostic; operators can switch LLM providers and inspect the agent configuration and inter-agent contracts without touching business logic.

## Capabilities and Constraints

- Supported formats: PDF, DOCX, XLSX; OCR available for scanned pages (Tesseract).
- Masking targets: ИНН, ФИО, addresses, dates, party roles, and user-defined data types.
- Marker styles: structured placeholder markers or opaque redaction blocks.
- Multi-agent pipeline: each agent has a named role, engine type (rules / model / hybrid / OCR), and produces traceable input/output logs.
- Auth: session-based (cookie), with silent token refresh; no tokens in JS.
- Data retention after masking: **undecided** — whether originals are stored, ephemeral, or client-local has not been specified and must not be fabricated in UI copy or reporting.
- SSR vs. SPA rendering mode: **undecided** — `ssr: true` is configured but the Docker image serves SPA only; must be resolved before server-dependent loaders/actions are written.
- UI language: Russian throughout.

## Brand Commitments

Product name: **TriemaMasker**. No logo, color palette, typeface, or other visual brand assets have been established yet.

## Evidence on Hand

- Full feature scaffold in `src/pages/masker/` (upload, process, review, report, history, model, settings).
- Entity models: `document`, `mask`, `rule-profile`, `agent` — all with typed fixtures and Zustand stores where state is needed.
- Feature modules: `document-upload`, `document-processing`, `mask-review`, `masking-report`, `document-history`, `model-settings`, `app-settings`.
- Backend at `https://42team.ru/api`; OpenAPI client generated via Orval (tags-split, react-query).
- No real assets (screenshots, testimonials, customer data) are available; fabrication is prohibited.

## Product Principles

1. **Operator in control.** Every AI decision is visible and overridable; the system never silently commits a replacement.
2. **Structure is sacred.** The masked document must be structurally and visually equivalent to the original; formatting degradation is a defect, not a trade-off.
3. **Compliance is evidence, not marketing.** 152-FZ alignment is expressed through the data model and audit trail, not copy claims.
4. **Pipeline transparency.** The agent layer is inspectable end-to-end — inputs, outputs, confidence, timing — so operators can diagnose and trust the result.
5. **One session, one outcome.** Upload-to-export is a single focused workflow; dead ends, lost context, and mode confusion are design failures.

## Accessibility & Inclusion

No product-specific accessibility requirements have been established beyond WCAG AA color contrast (enforced by the Astryx neutral theme). The tool is desktop-primary; mobile-responsive behavior is desirable but not a primary concern.
