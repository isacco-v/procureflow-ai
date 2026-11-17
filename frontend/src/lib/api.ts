import { z } from 'zod'

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL
const apiBaseUrl = (
  typeof configuredBaseUrl === 'string' && configuredBaseUrl.length > 0
    ? configuredBaseUrl
    : 'http://127.0.0.1:8000'
).replace(/\/$/, '')

export { apiBaseUrl }

const decimalSchema = z.string().regex(/^-?\d+(\.\d+)?$/)
const matchStatusSchema = z.enum(['MATCHED', 'EXCEPTION', 'NEEDS_REVIEW'])
const documentTypeSchema = z.enum([
  'purchase_order',
  'delivery_note',
  'invoice',
])
const findingCodeSchema = z.enum([
  'LINE_RECONCILED',
  'ORDERED_NOT_DELIVERED',
  'DELIVERED_NOT_ORDERED',
  'INVOICED_WITHOUT_DELIVERY',
  'DELIVERED_NOT_INVOICED',
  'INVOICED_NOT_ORDERED',
  'ORDERED_NOT_INVOICED',
  'PRICE_MISMATCH',
  'INCONSISTENT_UNIT_PRICE',
  'MISSING_UNIT_PRICE',
  'UNCERTAIN_PRODUCT_MAPPING',
  'MISSING_PURCHASE_ORDER',
  'MISSING_REFERENCE',
  'REFERENCE_MISMATCH',
  'CURRENCY_MISMATCH',
  'MISSING_CURRENCY',
  'UNIT_MISMATCH',
  'NO_LINES',
])

const healthResponseSchema = z.object({
  status: z.literal('ok'),
  service: z.string(),
  environment: z.string(),
  ai_mode: z.enum(['mock', 'openai']),
})

const supplierSchema = z.object({
  id: z.uuid(),
  code: z.string(),
  name: z.string(),
  synthetic: z.boolean(),
})

const documentLineSchema = z.object({
  line_number: z.number().int(),
  product_code: z.string().nullable(),
  description: z.string(),
  quantity: decimalSchema,
  unit: z.string(),
  unit_price: decimalSchema.nullable().optional(),
  currency: z.string().nullable().optional(),
  source_document_id: z.uuid(),
})

const purchaseOrderSchema = z.object({
  id: z.uuid(),
  number: z.string(),
  currency: z.string(),
  issued_on: z.string(),
  source_document_id: z.uuid(),
  lines: z.array(documentLineSchema),
})

const deliveryNoteSchema = z.object({
  id: z.uuid(),
  number: z.string(),
  purchase_order_number: z.string().nullable(),
  delivered_on: z.string(),
  source_document_id: z.uuid(),
  lines: z.array(documentLineSchema),
})

const invoiceSchema = z.object({
  id: z.uuid(),
  number: z.string(),
  purchase_order_number: z.string().nullable(),
  currency: z.string(),
  issued_on: z.string(),
  source_document_id: z.uuid(),
  lines: z.array(documentLineSchema),
})

const caseOriginSchema = z.enum(['synthetic_seed', 'upload'])

const caseSummarySchema = z.object({
  id: z.uuid(),
  reference: z.string(),
  title: z.string(),
  summary: z.string(),
  synthetic: z.boolean(),
  origin: caseOriginSchema,
  supplier: supplierSchema,
  latest_reconciliation_id: z.uuid().nullable(),
  latest_reconciliation_status: matchStatusSchema.nullable(),
})

const caseListSchema = z.object({
  cases: z.array(caseSummarySchema),
})

const caseDetailSchema = caseSummarySchema.extend({
  documents: z.array(
    z.object({
      id: z.uuid(),
      document_type: documentTypeSchema,
      document_number: z.string(),
      synthetic: z.boolean(),
      origin: caseOriginSchema,
      upload_id: z.uuid().nullable(),
    })
  ),
  purchase_order: purchaseOrderSchema.nullable(),
  delivery_notes: z.array(deliveryNoteSchema),
  invoices: z.array(invoiceSchema),
})

const sourceReferenceSchema = z.object({
  document_type: documentTypeSchema,
  document_number: z.string(),
  line_number: z.number().int().nullable(),
  document_id: z.uuid().nullable(),
})

const findingSchema = z.object({
  code: findingCodeSchema,
  status: matchStatusSchema,
  product_code: z.string().nullable(),
  message: z.string(),
  unit: z.string().nullable(),
  currency: z.string().nullable(),
  ordered_quantity: decimalSchema.nullable(),
  delivered_quantity: decimalSchema.nullable(),
  invoiced_quantity: decimalSchema.nullable(),
  quantity_difference: decimalSchema.nullable(),
  purchase_order_unit_price: decimalSchema.nullable(),
  invoice_unit_price: decimalSchema.nullable(),
  price_difference: decimalSchema.nullable(),
  source_references: z.array(sourceReferenceSchema),
})

const reconciliationSchema = z.object({
  id: z.uuid(),
  case_id: z.uuid(),
  status: matchStatusSchema,
  engine_version: z.string(),
  input_fingerprint: z.string(),
  created_at: z.string(),
  replayed: z.boolean(),
  findings: z.array(findingSchema),
})

const seedResponseSchema = z.object({
  synthetic: z.literal(true),
  cases_created: z.array(z.string()),
  cases_existing: z.array(z.string()),
})

const investigationStatusSchema = z.enum([
  'completed',
  'inconclusive',
  'failed',
  'budget_exceeded',
  'step_limit',
  'invalid_output',
  'timed_out',
])

const recommendedActionSchema = z.enum([
  'request_quantity_credit',
  'hold_for_price_review',
  'escalate_product_identity',
  'request_supplier_clarification',
  'inconclusive',
])

const investigationEventSchema = z.object({
  ordinal: z.number().int(),
  event_type: z.string(),
  tool_name: z.string().nullable(),
  summary: z.string(),
  payload: z.record(z.string(), z.unknown()),
  created_at: z.string(),
})

const prerequisiteSchema = z.object({
  kind: z.literal('future_delivery'),
  status: z.literal('unconfirmed'),
})

const investigationSchema = z.object({
  id: z.uuid(),
  case_id: z.uuid(),
  reconciliation_run_id: z.uuid(),
  status: investigationStatusSchema,
  ai_mode: z.enum(['mock', 'openai']),
  provider: z.string(),
  model_name: z.string(),
  reasoning_kind: z.enum(['deterministic_test_double', 'language_model']),
  mock_execution: z.boolean(),
  recommended_action: recommendedActionSchema.nullable(),
  review_required: z.literal(true),
  payment_authority: z.literal(false),
  summary: z.string().nullable(),
  findings: z.array(
    z.object({
      code: z.string(),
      summary: z.string(),
      evidence_labels: z.array(z.string()),
    })
  ),
  unresolved_issues: z.array(z.string()),
  citations: z.array(
    z.object({
      policy_code: z.string(),
      section_code: z.string(),
      version: z.string(),
      heading: z.string(),
      excerpt: z.string(),
      content_trust: z.literal('untrusted'),
    })
  ),
  evidence: z.array(
    z.object({
      tool_name: z.string(),
      record_type: z.string(),
      record_id: z.uuid().nullable(),
      label: z.string(),
    })
  ),
  events: z.array(investigationEventSchema),
  error_code: z.string().nullable(),
  error_detail: z.string().nullable(),
  input_tokens: z.number().int(),
  output_tokens: z.number().int(),
  estimated_cost_usd: decimalSchema,
  iteration_count: z.number().int(),
  tool_call_count: z.number().int(),
  attempt: z.number().int(),
  evidence_validated: z.boolean(),
  observed_facts: z.array(z.string()),
  possible_explanations: z.array(z.string()),
  missing_evidence: z.array(z.string()),
  next_actions: z.array(z.string()),
  prerequisites: z.array(prerequisiteSchema),
  replayed: z.boolean(),
  started_at: z.string(),
  finished_at: z.string(),
})

export type HealthResponse = z.infer<typeof healthResponseSchema>
export type MatchStatus = z.infer<typeof matchStatusSchema>
export type CaseSummary = z.infer<typeof caseSummarySchema>
export type CaseDetail = z.infer<typeof caseDetailSchema>
export type DocumentLine = z.infer<typeof documentLineSchema>
export type Reconciliation = z.infer<typeof reconciliationSchema>
export type Finding = z.infer<typeof findingSchema>
export type SeedResponse = z.infer<typeof seedResponseSchema>
export type Investigation = z.infer<typeof investigationSchema>

export class ApiError extends Error {
  readonly status: number
  readonly code: string | undefined

  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

/** @deprecated Use ApiError. Kept so existing health callers keep a named type. */
export class HealthCheckError extends ApiError {
  constructor(message: string) {
    super(message, 0)
    this.name = 'HealthCheckError'
  }
}

async function requestJson(path: string, init?: RequestInit): Promise<unknown> {
  let response: Response
  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...init?.headers,
      },
    })
  } catch {
    throw new ApiError(`Could not reach the API at ${apiBaseUrl}.`, 0)
  }

  let body: unknown = null
  if (response.status !== 204) {
    try {
      body = await response.json()
    } catch {
      body = null
    }
  }

  if (!response.ok) {
    const record =
      body && typeof body === 'object'
        ? (body as { code?: unknown; detail?: unknown })
        : {}
    const detail =
      typeof record.detail === 'string'
        ? record.detail
        : `Request failed with status ${response.status}.`
    const code = typeof record.code === 'string' ? record.code : undefined
    throw new ApiError(detail, response.status, code)
  }
  return body
}

function parse<T>(schema: z.ZodType<T>, body: unknown, label: string): T {
  const parsed = schema.safeParse(body)
  if (!parsed.success) {
    throw new ApiError(`${label} returned an unexpected payload.`, 200)
  }
  return parsed.data
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  try {
    const body = await requestJson('/health', { signal })
    return parse(healthResponseSchema, body, 'Health check')
  } catch (error) {
    if (error instanceof ApiError) {
      throw new HealthCheckError(error.message)
    }
    throw error
  }
}

export async function listCases(signal?: AbortSignal): Promise<CaseSummary[]> {
  const body = await requestJson('/api/v1/cases', { signal })
  return parse(caseListSchema, body, 'Case list').cases
}

export async function getCase(
  caseId: string,
  signal?: AbortSignal
): Promise<CaseDetail> {
  const body = await requestJson(`/api/v1/cases/${caseId}`, { signal })
  return parse(caseDetailSchema, body, 'Case detail')
}

export async function getLatestReconciliation(
  caseId: string,
  signal?: AbortSignal
): Promise<Reconciliation | null> {
  try {
    const body = await requestJson(`/api/v1/cases/${caseId}/reconciliation`, {
      signal,
    })
    return parse(reconciliationSchema, body, 'Reconciliation')
  } catch (error) {
    if (
      error instanceof ApiError &&
      error.status === 404 &&
      error.code === 'reconciliation_not_found'
    ) {
      return null
    }
    throw error
  }
}

export async function runReconciliation(
  caseId: string
): Promise<Reconciliation> {
  const body = await requestJson(`/api/v1/cases/${caseId}/reconciliation`, {
    method: 'POST',
  })
  return parse(reconciliationSchema, body, 'Reconciliation')
}

export async function seedSyntheticCases(): Promise<SeedResponse> {
  const body = await requestJson('/api/v1/dev/seed', { method: 'POST' })
  return parse(seedResponseSchema, body, 'Synthetic seed')
}

export async function getInvestigationForRun(
  caseId: string,
  runId: string,
  signal?: AbortSignal
): Promise<Investigation | null> {
  try {
    const body = await requestJson(
      `/api/v1/cases/${caseId}/reconciliation/${runId}/investigation`,
      { signal }
    )
    return parse(investigationSchema, body, 'Investigation')
  } catch (error) {
    if (
      error instanceof ApiError &&
      error.status === 404 &&
      error.code === 'investigation_not_found'
    ) {
      return null
    }
    throw error
  }
}

export async function startInvestigation(
  caseId: string,
  runId: string,
  options?: { newAttempt?: boolean; idempotencyKey?: string }
): Promise<Investigation> {
  const headers: Record<string, string> = {}
  if (options?.newAttempt) {
    headers['X-Investigation-Attempt'] = 'new'
    headers['Idempotency-Key'] = options.idempotencyKey ?? crypto.randomUUID()
  }
  const body = await requestJson(
    `/api/v1/cases/${caseId}/reconciliation/${runId}/investigations`,
    { method: 'POST', headers }
  )
  return parse(investigationSchema, body, 'Investigation')
}

const uploadStatusSchema = z.enum(['needs_review', 'accepted', 'failed'])
const extractorSchema = z.enum(['mock', 'openai'])
const reasoningKindSchema = z.enum([
  'deterministic_test_double',
  'language_model',
])

const extractedLineSchema = z.object({
  line_number: z.number().int().nullable(),
  product_code: z.string().nullable(),
  description: z.string().nullable(),
  quantity: z.string().nullable(),
  unit: z.string().nullable(),
  unit_price: z.string().nullable(),
  line_total: z.string().nullable(),
})

const extractedDocumentSchema = z.object({
  document_type: documentTypeSchema.nullable(),
  document_number: z.string().nullable(),
  supplier_name: z.string().nullable(),
  supplier_code: z.string().nullable(),
  purchase_order_number: z.string().nullable(),
  document_date: z.string().nullable(),
  currency: z.string().nullable(),
  lines: z.array(extractedLineSchema),
  net_amount: z.string().nullable(),
  tax_rate_percent: z.string().nullable(),
  tax_amount: z.string().nullable(),
  amount_due: z.string().nullable(),
  uncertainties: z.array(z.string()),
  source_references: z.array(
    z.object({
      field: z.string(),
      page_number: z.number().int(),
      snippet: z.string(),
    })
  ),
})

const validationSchema = z.object({
  status: z.enum(['ready', 'blocked']),
  blocking: z.boolean(),
  warnings: z.array(
    z.object({
      code: z.string(),
      severity: z.enum(['blocking', 'advisory']),
      message: z.string(),
      field: z.string().nullable(),
    })
  ),
  normalized: z.record(z.string(), z.unknown()).nullable(),
  computed: z.record(z.string(), z.unknown()),
})

const uploadSummarySchema = z.object({
  id: z.uuid(),
  original_filename: z.string(),
  byte_size: z.number().int(),
  sha256: z.string(),
  page_count: z.number().int().nullable(),
  status: uploadStatusSchema,
  stages: z.array(z.string()),
  error_code: z.string().nullable(),
  error_detail: z.string().nullable(),
  image_only: z.boolean(),
  text_extractable: z.boolean(),
  ocr_applied: z.literal(false),
  ocr_implemented: z.literal(false),
  content_source: z.literal('page_text'),
  extractor: extractorSchema.nullable(),
  mocked: z.boolean().nullable(),
  model_name: z.string().nullable(),
  reasoning_kind: reasoningKindSchema.nullable(),
  document_type: documentTypeSchema.nullable(),
  document_number: z.string().nullable(),
  accepted_case_id: z.uuid().nullable(),
  duplicate: z.boolean(),
  created_at: z.string(),
})

const uploadDetailSchema = uploadSummarySchema.extend({
  media_type: z.string(),
  char_count: z.number().int(),
  pdf_metadata: z.record(z.string(), z.string()),
  pages: z.array(
    z.object({
      page_number: z.number().int(),
      text: z.string(),
      blocks: z.array(
        z.object({
          text: z.string(),
          bbox: z.array(z.number()),
        })
      ),
    })
  ),
  extraction: extractedDocumentSchema.nullable(),
  validation: validationSchema.nullable(),
  prompt_injection_flags: z.array(z.string()),
  input_tokens: z.number().int().nullable(),
  output_tokens: z.number().int().nullable(),
  estimated_cost_usd: decimalSchema.nullable(),
})

const uploadListSchema = z.object({
  documents: z.array(uploadSummarySchema),
})

const acceptDocumentSchema = z.object({
  document_id: z.uuid(),
  case_id: z.uuid(),
  case_reference: z.string(),
  procurement_document_id: z.uuid(),
  origin: z.literal('upload'),
  synthetic: z.literal(false),
  replayed: z.boolean(),
  reconciliation_id: z.uuid().nullable(),
  reconciliation_status: matchStatusSchema.nullable(),
  reconciliation_error: z.string().nullable(),
})

export type UploadedDocumentSummary = z.infer<typeof uploadSummarySchema>
export type UploadedDocumentDetail = z.infer<typeof uploadDetailSchema>
export type AcceptedDocument = z.infer<typeof acceptDocumentSchema>

export async function listDocuments(
  signal?: AbortSignal
): Promise<UploadedDocumentSummary[]> {
  const body = await requestJson('/api/v1/documents', { signal })
  return parse(uploadListSchema, body, 'Document list').documents
}

export async function getDocument(
  documentId: string,
  signal?: AbortSignal
): Promise<UploadedDocumentDetail> {
  const body = await requestJson(`/api/v1/documents/${documentId}`, { signal })
  return parse(uploadDetailSchema, body, 'Document detail')
}

export async function uploadDocument(
  file: File
): Promise<UploadedDocumentDetail> {
  const form = new FormData()
  form.append('file', file)
  let response: Response
  try {
    response = await fetch(`${apiBaseUrl}/api/v1/documents`, {
      method: 'POST',
      body: form,
      headers: { Accept: 'application/json' },
    })
  } catch {
    throw new ApiError(`Could not reach the API at ${apiBaseUrl}.`, 0)
  }
  let body: unknown
  try {
    body = await response.json()
  } catch {
    body = null
  }
  if (!response.ok) {
    const record =
      body && typeof body === 'object'
        ? (body as { code?: unknown; detail?: unknown })
        : {}
    const detail =
      typeof record.detail === 'string'
        ? record.detail
        : `Request failed with status ${response.status}.`
    const code = typeof record.code === 'string' ? record.code : undefined
    throw new ApiError(detail, response.status, code)
  }
  return parse(uploadDetailSchema, body, 'Document upload')
}

export async function acceptDocument(
  documentId: string
): Promise<AcceptedDocument> {
  const body = await requestJson(`/api/v1/documents/${documentId}/accept`, {
    method: 'POST',
  })
  return parse(acceptDocumentSchema, body, 'Document acceptance')
}
