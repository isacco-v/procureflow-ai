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

const caseSummarySchema = z.object({
  id: z.uuid(),
  reference: z.string(),
  title: z.string(),
  summary: z.string(),
  synthetic: z.boolean(),
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

export type HealthResponse = z.infer<typeof healthResponseSchema>
export type MatchStatus = z.infer<typeof matchStatusSchema>
export type CaseSummary = z.infer<typeof caseSummarySchema>
export type CaseDetail = z.infer<typeof caseDetailSchema>
export type DocumentLine = z.infer<typeof documentLineSchema>
export type Reconciliation = z.infer<typeof reconciliationSchema>
export type Finding = z.infer<typeof findingSchema>
export type SeedResponse = z.infer<typeof seedResponseSchema>

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
