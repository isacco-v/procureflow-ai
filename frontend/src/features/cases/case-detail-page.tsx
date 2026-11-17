import { type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from '@tanstack/react-router'
import {
  getCase,
  getLatestReconciliation,
  runReconciliation,
  type CaseDetail,
  type DocumentLine,
  type Finding,
  type Reconciliation,
} from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { InvestigationPanel } from './investigation-panel'
import { StatusBadge } from './status-badge'

export function CaseDetailPage() {
  const { caseId } = useParams({ from: '/_authenticated/cases/$caseId' })
  const queryClient = useQueryClient()
  const caseQuery = useQuery({
    queryKey: ['cases', caseId],
    queryFn: ({ signal }) => getCase(caseId, signal),
  })
  const reconciliationQuery = useQuery({
    queryKey: ['cases', caseId, 'reconciliation'],
    queryFn: ({ signal }) => getLatestReconciliation(caseId, signal),
  })
  const reconcileMutation = useMutation({
    mutationFn: () => runReconciliation(caseId),
    onSuccess: async (result) => {
      queryClient.setQueryData(['cases', caseId, 'reconciliation'], result)
      await queryClient.invalidateQueries({ queryKey: ['cases'] })
    },
  })
  const reconciliation = reconcileMutation.data ?? reconciliationQuery.data

  return (
    <>
      <Header>
        <Search className='me-auto' />
        <ThemeSwitch />
        <ConfigDrawer />
      </Header>
      <Main>
        <div className='mb-6 space-y-3'>
          <Link
            to='/cases'
            className='text-sm text-muted-foreground underline-offset-4 hover:underline'
          >
            All cases
          </Link>
          {caseQuery.isPending ? (
            <p className='text-sm text-muted-foreground'>Loading case…</p>
          ) : null}
          {caseQuery.isError ? (
            <p className='text-sm text-destructive' role='alert'>
              {caseQuery.error.message}
            </p>
          ) : null}
          {caseQuery.data ? (
            <>
              <div className='flex flex-wrap items-center gap-2'>
                <h1 className='text-2xl font-bold tracking-tight'>
                  {caseQuery.data.title}
                </h1>
                <Badge variant='outline'>
                  {caseQuery.data.origin === 'upload'
                    ? 'Uploaded documents'
                    : 'Synthetic seed'}
                </Badge>
                {reconciliation ? (
                  <StatusBadge status={reconciliation.status} />
                ) : null}
              </div>
              <p className='max-w-3xl text-muted-foreground'>
                {caseQuery.data.reference} · {caseQuery.data.supplier.name}.{' '}
                {caseQuery.data.summary}
              </p>
              <p className='max-w-3xl text-sm text-muted-foreground'>
                {caseQuery.data.origin === 'upload'
                  ? 'Accepted from uploaded PDFs. The matcher compares those stored lines and does not recalculate them from the file.'
                  : 'Loaded by the synthetic seed. Reconciliation and investigation read these stored lines. They do not re-read a PDF, and they do not change the historical live results.'}
              </p>
            </>
          ) : null}
        </div>

        {caseQuery.data ? (
          <div className='space-y-4'>
            <div className='flex flex-wrap items-center gap-3'>
              <Button
                onClick={() => reconcileMutation.mutate()}
                disabled={reconcileMutation.isPending}
              >
                {reconcileMutation.isPending
                  ? 'Reconciling…'
                  : 'Run reconciliation'}
              </Button>
              <p className='text-sm text-muted-foreground'>
                Compares ordered, delivered, and invoiced quantities and unit
                prices. Product lines match on their identifier only.
              </p>
            </div>
            {reconcileMutation.isError ? (
              <p className='text-sm text-destructive' role='alert'>
                {reconcileMutation.error.message}
              </p>
            ) : null}

            <DocumentCard
              title='Purchase order'
              empty='This case has no purchase order.'
            >
              {caseQuery.data.purchase_order ? (
                <DocumentBlock
                  number={caseQuery.data.purchase_order.number}
                  meta={`${caseQuery.data.purchase_order.issued_on} · ${caseQuery.data.purchase_order.currency}`}
                  uploadId={uploadIdFor(
                    caseQuery.data,
                    caseQuery.data.purchase_order.source_document_id
                  )}
                  lines={caseQuery.data.purchase_order.lines}
                  showPrice
                />
              ) : null}
            </DocumentCard>

            <DocumentCard
              title='Delivery notes'
              empty='This case has no delivery notes.'
            >
              {caseQuery.data.delivery_notes.length > 0
                ? caseQuery.data.delivery_notes.map((note) => (
                    <DocumentBlock
                      key={note.id}
                      number={note.number}
                      meta={`${note.delivered_on} · purchase order ${note.purchase_order_number ?? 'not cited'}`}
                      uploadId={uploadIdFor(
                        caseQuery.data,
                        note.source_document_id
                      )}
                      lines={note.lines}
                    />
                  ))
                : null}
            </DocumentCard>

            <DocumentCard title='Invoices' empty='This case has no invoices.'>
              {caseQuery.data.invoices.length > 0
                ? caseQuery.data.invoices.map((invoice) => (
                    <DocumentBlock
                      key={invoice.id}
                      number={invoice.number}
                      meta={`${invoice.issued_on} · ${invoice.currency} · purchase order ${invoice.purchase_order_number ?? 'not cited'}`}
                      uploadId={uploadIdFor(
                        caseQuery.data,
                        invoice.source_document_id
                      )}
                      lines={invoice.lines}
                      showPrice
                    />
                  ))
                : null}
            </DocumentCard>

            <ReconciliationCard
              reconciliation={reconciliation ?? null}
              isPending={reconciliationQuery.isPending}
              isError={reconciliationQuery.isError}
              errorMessage={
                reconciliationQuery.error instanceof Error
                  ? reconciliationQuery.error.message
                  : undefined
              }
            />
            <InvestigationPanel
              caseId={caseId}
              reconciliation={reconciliation ?? null}
              reconciliationLoading={
                reconciliationQuery.isPending && reconcileMutation.data == null
              }
              reconciliationUnavailable={
                reconciliationQuery.isError && reconcileMutation.data == null
              }
            />
          </div>
        ) : null}
      </Main>
    </>
  )
}

function DocumentCard({
  title,
  empty,
  children,
}: {
  title: string
  empty: string
  children: ReactNode
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>
          Lines stored on this case. Seeded rows and accepted uploads use the
          same tables.
        </CardDescription>
      </CardHeader>
      <CardContent className='space-y-6'>
        {children ?? <p className='text-sm text-muted-foreground'>{empty}</p>}
      </CardContent>
    </Card>
  )
}

function DocumentBlock({
  number,
  meta,
  uploadId,
  lines,
  showPrice = false,
}: {
  number: string
  meta: string
  uploadId: string | null
  lines: DocumentLine[]
  showPrice?: boolean
}) {
  return (
    <div className='space-y-2'>
      <div>
        <h2 className='font-medium'>{number}</h2>
        <p className='text-sm text-muted-foreground'>{meta}</p>
        {uploadId ? (
          <Link
            to='/documents/$documentId'
            params={{ documentId: uploadId }}
            className='text-sm font-medium underline-offset-4 hover:underline'
          >
            View parsed upload
          </Link>
        ) : (
          <p className='text-xs text-muted-foreground'>
            Stored with the case. This row is not an uploaded PDF.
          </p>
        )}
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Line</TableHead>
            <TableHead>Product</TableHead>
            <TableHead>Description</TableHead>
            <TableHead className='text-right'>Quantity</TableHead>
            <TableHead>Unit</TableHead>
            {showPrice ? (
              <TableHead className='text-right'>Unit price</TableHead>
            ) : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {lines.map((line) => (
            <TableRow key={line.line_number}>
              <TableCell>{line.line_number}</TableCell>
              <TableCell>{line.product_code ?? 'No identifier'}</TableCell>
              <TableCell>{line.description}</TableCell>
              <TableCell className='text-right'>{line.quantity}</TableCell>
              <TableCell>{line.unit}</TableCell>
              {showPrice ? (
                <TableCell className='text-right'>
                  {line.unit_price
                    ? `${line.unit_price} ${line.currency ?? ''}`
                    : 'Not set'}
                </TableCell>
              ) : null}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function ReconciliationCard({
  reconciliation,
  isPending,
  isError,
  errorMessage,
}: {
  reconciliation: Reconciliation | null
  isPending: boolean
  isError: boolean
  errorMessage?: string
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Reconciliation</CardTitle>
        <CardDescription>
          Findings come from the deterministic matcher. A missing product
          identifier stays unresolved even when descriptions look similar.
        </CardDescription>
      </CardHeader>
      <CardContent className='space-y-4'>
        {isPending ? (
          <p className='text-sm text-muted-foreground'>
            Checking for a stored run…
          </p>
        ) : null}
        {isError ? (
          <p className='text-sm text-destructive' role='alert'>
            {errorMessage}
          </p>
        ) : null}
        {!isPending && !isError && reconciliation === null ? (
          <p className='text-sm text-muted-foreground'>
            Reconciliation has not been run for this case.
          </p>
        ) : null}
        {reconciliation ? (
          <div className='space-y-4'>
            <div className='flex flex-wrap items-center gap-2 text-sm'>
              <StatusBadge status={reconciliation.status} />
              <span className='text-muted-foreground'>
                Engine {reconciliation.engine_version}
                {reconciliation.replayed
                  ? ' · existing run returned unchanged'
                  : ''}
              </span>
            </div>
            {reconciliation.findings.map((finding) => (
              <div
                key={`${finding.code}-${finding.product_code ?? 'none'}-${finding.message}`}
                className='space-y-2 rounded-md border p-3'
              >
                <div className='flex flex-wrap items-center gap-2'>
                  <span className='font-medium'>
                    {findingLabels[finding.code]}
                  </span>
                  <Badge variant='outline'>{finding.code}</Badge>
                  <StatusBadge status={finding.status} />
                  {finding.product_code ? (
                    <Badge variant='outline'>{finding.product_code}</Badge>
                  ) : null}
                </div>
                <p className='text-sm'>{finding.message}</p>
                {hasQuantityGap(finding.quantity_difference) ? (
                  <p className='text-sm font-medium'>
                    Quantity gap {finding.quantity_difference}{' '}
                    {finding.unit ?? ''}
                  </p>
                ) : null}
                <dl className='grid gap-2 text-sm sm:grid-cols-3'>
                  <Quantity
                    label='Ordered'
                    value={finding.ordered_quantity}
                    unit={finding.unit}
                  />
                  <Quantity
                    label='Delivered'
                    value={finding.delivered_quantity}
                    unit={finding.unit}
                  />
                  <Quantity
                    label='Invoiced'
                    value={finding.invoiced_quantity}
                    unit={finding.unit}
                  />
                </dl>
                {finding.purchase_order_unit_price !== null ||
                finding.invoice_unit_price !== null ? (
                  <p className='text-sm'>
                    Purchase order unit price{' '}
                    {finding.purchase_order_unit_price ?? 'not set'}. Invoice
                    unit price {finding.invoice_unit_price ?? 'not set'}.
                    {finding.price_difference !== null
                      ? ` Difference ${finding.price_difference} ${finding.currency ?? ''}.`
                      : ''}
                  </p>
                ) : null}
                <p className='text-xs text-muted-foreground'>
                  Sources:{' '}
                  {finding.source_references
                    .map((reference) =>
                      reference.line_number === null
                        ? reference.document_number
                        : `${reference.document_number} line ${reference.line_number}`
                    )
                    .join(', ') || 'none'}
                </p>
              </div>
            ))}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

function uploadIdFor(detail: CaseDetail, sourceDocumentId: string) {
  return (
    detail.documents.find((document) => document.id === sourceDocumentId)
      ?.upload_id ?? null
  )
}

const findingLabels: Record<Finding['code'], string> = {
  LINE_RECONCILED: 'Line reconciled',
  ORDERED_NOT_DELIVERED: 'Ordered, not delivered',
  DELIVERED_NOT_ORDERED: 'Delivered, not ordered',
  INVOICED_WITHOUT_DELIVERY: 'Invoiced without delivery',
  DELIVERED_NOT_INVOICED: 'Delivered, not invoiced',
  INVOICED_NOT_ORDERED: 'Invoiced, not ordered',
  ORDERED_NOT_INVOICED: 'Ordered, not invoiced',
  PRICE_MISMATCH: 'Price mismatch',
  INCONSISTENT_UNIT_PRICE: 'Inconsistent unit price',
  MISSING_UNIT_PRICE: 'Missing unit price',
  UNCERTAIN_PRODUCT_MAPPING: 'Uncertain product mapping',
  MISSING_PURCHASE_ORDER: 'Missing purchase order',
  MISSING_REFERENCE: 'Missing reference',
  REFERENCE_MISMATCH: 'Reference mismatch',
  CURRENCY_MISMATCH: 'Currency mismatch',
  MISSING_CURRENCY: 'Missing currency',
  UNIT_MISMATCH: 'Unit mismatch',
  NO_LINES: 'No lines',
}

function hasQuantityGap(value: string | null) {
  return value !== null && !/^0+(\.0+)?$/.test(value)
}

function Quantity({
  label,
  value,
  unit,
}: {
  label: string
  value: string | null
  unit: string | null
}) {
  return (
    <div>
      <dt className='text-muted-foreground'>{label}</dt>
      <dd className='font-medium'>
        {value === null ? 'Not compared' : `${value} ${unit ?? ''}`}
      </dd>
    </div>
  )
}
