import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from '@tanstack/react-router'
import { ApiError, acceptDocument, getDocument } from '@/lib/api'
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
import { ExtractorBadge, StatusBadge, labelType } from './documents-page'

export function DocumentDetailPage() {
  const { documentId } = useParams({
    from: '/_authenticated/documents/$documentId',
  })
  const queryClient = useQueryClient()
  const documentQuery = useQuery({
    queryKey: ['documents', documentId],
    queryFn: ({ signal }) => getDocument(documentId, signal),
  })
  const acceptMutation = useMutation({
    mutationFn: () => acceptDocument(documentId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['documents'] })
      await queryClient.invalidateQueries({ queryKey: ['cases'] })
    },
  })
  const document = documentQuery.data
  const acceptedCaseId =
    acceptMutation.data?.case_id ?? document?.accepted_case_id ?? null
  const blocking = document?.validation?.blocking === true
  const canAccept =
    document?.status === 'needs_review' &&
    document.extraction !== null &&
    blocking === false

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
            to='/documents'
            className='text-sm text-muted-foreground underline-offset-4 hover:underline'
          >
            All documents
          </Link>
          {documentQuery.isPending ? (
            <p className='text-sm text-muted-foreground'>Loading document…</p>
          ) : null}
          {documentQuery.isError ? (
            <p className='text-sm text-destructive' role='alert'>
              {documentQuery.error.message}
            </p>
          ) : null}
          {document ? (
            <>
              <div className='flex flex-wrap items-center gap-2'>
                <h1 className='text-2xl font-bold tracking-tight'>
                  {document.original_filename}
                </h1>
                <StatusBadge status={document.status} />
                <ExtractorBadge mocked={document.mocked} />
              </div>
              <p className='max-w-3xl text-muted-foreground'>
                File name is display only. Classification uses page text.
                {document.document_number
                  ? ` Read as ${labelType(document.document_type)} ${document.document_number}.`
                  : ' No document number was read.'}
              </p>
            </>
          ) : null}
        </div>

        {document ? (
          <div className='space-y-6'>
            <ExtractionNotice document={document} />
            {document.error_detail ? (
              <p className='text-sm text-destructive' role='alert'>
                {document.error_detail}
              </p>
            ) : null}
            <Card>
              <CardHeader>
                <CardTitle>Acceptance</CardTitle>
                <CardDescription>
                  Accepting copies the normalized fields into a new procurement
                  case, or into an existing upload case with the same purchase
                  order. Seeded demonstration records are not changed.
                </CardDescription>
              </CardHeader>
              <CardContent className='space-y-3'>
                {canAccept ? (
                  <Button
                    onClick={() => acceptMutation.mutate()}
                    disabled={acceptMutation.isPending}
                  >
                    {acceptMutation.isPending
                      ? 'Accepting…'
                      : 'Accept extracted data'}
                  </Button>
                ) : null}
                {blocking ? (
                  <p className='text-sm text-muted-foreground'>
                    Blocking warnings must be resolved before this extraction
                    can be accepted. The stated values were not corrected.
                  </p>
                ) : null}
                {document.image_only ? (
                  <p className='text-sm text-muted-foreground'>
                    There is no extraction to accept.
                  </p>
                ) : null}
                {acceptMutation.isError ? (
                  <div className='space-y-1' role='alert'>
                    <p className='text-sm text-destructive'>
                      {acceptMutation.error.message}
                    </p>
                    {acceptMutation.error instanceof ApiError &&
                    acceptMutation.error.code ===
                      'procurement_record_exists' ? (
                      <p className='text-sm text-muted-foreground'>
                        The existing record was left unchanged. On the seeded
                        database this protects PO, delivery, and invoice numbers
                        that already belong to a demonstration case. The upload
                        walkthrough runs on a separate database.
                      </p>
                    ) : null}
                  </div>
                ) : null}
                {acceptedCaseId ? (
                  <Link
                    to='/cases/$caseId'
                    params={{ caseId: acceptedCaseId }}
                    className='text-sm font-medium underline-offset-4 hover:underline'
                  >
                    Open procurement case
                    {acceptMutation.data
                      ? ` ${acceptMutation.data.case_reference}`
                      : ''}
                  </Link>
                ) : null}
                {acceptMutation.data?.reconciliation_status ? (
                  <p className='text-sm text-muted-foreground'>
                    Reconciliation status:{' '}
                    {acceptMutation.data.reconciliation_status}. This did not
                    approve a payment.
                  </p>
                ) : null}
                {acceptMutation.data?.reconciliation_error ? (
                  <p className='text-sm text-destructive' role='alert'>
                    {acceptMutation.data.reconciliation_error}
                  </p>
                ) : null}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Extracted fields</CardTitle>
                <CardDescription>
                  Missing values stay empty. Source snippets point at the page
                  text that was read.
                </CardDescription>
              </CardHeader>
              <CardContent className='space-y-4'>
                {document.extraction ? (
                  <>
                    <dl className='grid gap-3 sm:grid-cols-2'>
                      <Field
                        label='Document type'
                        value={labelType(document.extraction.document_type)}
                      />
                      <Field
                        label='Document number'
                        value={document.extraction.document_number}
                      />
                      <Field
                        label='Supplier'
                        value={document.extraction.supplier_name}
                      />
                      <Field
                        label='Supplier code'
                        value={document.extraction.supplier_code}
                      />
                      <Field
                        label='Purchase order'
                        value={document.extraction.purchase_order_number}
                      />
                      <Field
                        label='Date'
                        value={document.extraction.document_date}
                      />
                      <Field
                        label='Currency'
                        value={document.extraction.currency}
                      />
                      <Field
                        label='Net amount'
                        value={document.extraction.net_amount}
                      />
                      <Field
                        label='Tax rate'
                        value={document.extraction.tax_rate_percent}
                      />
                      <Field
                        label='Tax amount'
                        value={document.extraction.tax_amount}
                      />
                      <Field
                        label='Amount due'
                        value={document.extraction.amount_due}
                      />
                    </dl>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Line</TableHead>
                          <TableHead>Product code</TableHead>
                          <TableHead>Description</TableHead>
                          <TableHead>Qty</TableHead>
                          <TableHead>Unit</TableHead>
                          <TableHead>Unit price</TableHead>
                          <TableHead>Line amount</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {document.extraction.lines.map((line, index) => (
                          <TableRow
                            key={`${line.line_number ?? 'line'}-${index}`}
                          >
                            <TableCell>{line.line_number ?? '—'}</TableCell>
                            <TableCell>
                              {line.product_code ?? 'Not stated'}
                            </TableCell>
                            <TableCell>{line.description ?? '—'}</TableCell>
                            <TableCell>{line.quantity ?? '—'}</TableCell>
                            <TableCell>{line.unit ?? '—'}</TableCell>
                            <TableCell>{line.unit_price ?? '—'}</TableCell>
                            <TableCell>{line.line_total ?? '—'}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                    {document.extraction.uncertainties.length > 0 ? (
                      <ul className='list-disc space-y-1 ps-5 text-sm text-muted-foreground'>
                        {document.extraction.uncertainties.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    ) : null}
                  </>
                ) : (
                  <p className='text-sm text-muted-foreground'>
                    No structured extraction is stored.
                  </p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Validation</CardTitle>
                <CardDescription>
                  Money and quantities are checked with decimal arithmetic in
                  application code. A model does not calculate them.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {document.validation ? (
                  <div className='space-y-3'>
                    <Badge variant='outline'>
                      {document.validation.blocking
                        ? 'Blocked'
                        : 'Ready for review'}
                    </Badge>
                    <ul className='space-y-2'>
                      {document.validation.warnings.length === 0 ? (
                        <li className='text-sm text-muted-foreground'>
                          No validation warnings. Acceptance is still explicit.
                        </li>
                      ) : (
                        document.validation.warnings.map((warning, index) => (
                          <li
                            key={`${warning.code}-${index}`}
                            className='text-sm'
                          >
                            <Badge variant='outline' className='me-2'>
                              {warning.severity}
                            </Badge>
                            {warning.message}
                          </li>
                        ))
                      )}
                    </ul>
                  </div>
                ) : (
                  <p className='text-sm text-muted-foreground'>
                    This document was not validated.
                  </p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Source references</CardTitle>
                <CardDescription>
                  Snippets are untrusted document text.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {document.extraction &&
                document.extraction.source_references.length > 0 ? (
                  <ul className='space-y-2'>
                    {document.extraction.source_references.map(
                      (item, index) => (
                        <li key={`${item.field}-${index}`} className='text-sm'>
                          <span className='font-medium'>
                            {labelField(item.field)}, page {item.page_number}:
                          </span>{' '}
                          <span className='text-muted-foreground'>
                            {item.snippet}
                          </span>
                        </li>
                      )
                    )}
                  </ul>
                ) : (
                  <p className='text-sm text-muted-foreground'>
                    No source snippets were recorded.
                  </p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Parsed text</CardTitle>
                <CardDescription>
                  {document.page_count ?? 0} page
                  {document.page_count === 1 ? '' : 's'}. SHA-256{' '}
                  {document.sha256}. PDF metadata is not used to classify the
                  file.
                </CardDescription>
              </CardHeader>
              <CardContent className='space-y-4'>
                {Object.keys(document.pdf_metadata).length > 0 ? (
                  <p className='text-sm text-muted-foreground'>
                    Metadata title: {document.pdf_metadata.title ?? 'none'}
                  </p>
                ) : null}
                {document.pages.map((page) => (
                  <div key={page.page_number}>
                    <h2 className='mb-2 text-sm font-medium'>
                      Page {page.page_number}
                    </h2>
                    <pre className='max-h-80 overflow-auto rounded-md border p-3 text-xs whitespace-pre-wrap'>
                      {page.text || 'No extractable text on this page.'}
                    </pre>
                  </div>
                ))}
                {document.mocked === true ? (
                  <p className='text-sm text-muted-foreground'>
                    Token count {document.input_tokens ?? 0} in /{' '}
                    {document.output_tokens ?? 0} out. Estimated cost{' '}
                    {document.estimated_cost_usd ?? '0'} USD. A mock extraction
                    records zero because it does not call a model.
                  </p>
                ) : null}
                {document.mocked === false ? (
                  <p className='text-sm text-muted-foreground'>
                    Live model {document.model_name}. Estimated cost{' '}
                    {document.estimated_cost_usd ?? '0'} USD. This is a
                    price-table estimate, not an invoice.
                  </p>
                ) : null}
              </CardContent>
            </Card>
          </div>
        ) : null}
      </Main>
    </>
  )
}

function ExtractionNotice({
  document,
}: {
  document: {
    image_only: boolean
    mocked: boolean | null
    model_name: string | null
    prompt_injection_flags: string[]
  }
}) {
  if (document.image_only) {
    return (
      <p className='rounded-md border px-4 py-3 text-sm' role='status'>
        This PDF has no extractable text. OCR and vision are not implemented, so
        the page image was not read and no fields were inferred.
      </p>
    )
  }
  if (document.mocked === true) {
    return (
      <p className='rounded-md border px-4 py-3 text-sm' role='status'>
        Mock extraction ({document.model_name}). This is a deterministic test
        double for the synthetic layouts. It is not a language model and it is
        not a measure of model accuracy.
        {document.prompt_injection_flags.length > 0
          ? ` Instruction-like text was flagged and ignored: ${document.prompt_injection_flags.join(', ')}.`
          : ''}
      </p>
    )
  }
  if (document.mocked === false) {
    return (
      <p className='rounded-md border px-4 py-3 text-sm' role='status'>
        Live LLM extraction with {document.model_name}. Review every field
        before accepting it. The model does not calculate the reconciliation.
      </p>
    )
  }
  return null
}

function labelField(field: string) {
  return field.replace(/_/g, ' ')
}

function Field({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <dt className='text-xs text-muted-foreground'>{label}</dt>
      <dd>{value && value.length > 0 ? value : '—'}</dd>
    </div>
  )
}
