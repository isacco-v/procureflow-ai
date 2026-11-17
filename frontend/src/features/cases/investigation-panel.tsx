import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  startInvestigation,
  getInvestigationForRun,
  type Investigation,
  type Reconciliation,
} from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'

const actionLabels: Record<
  NonNullable<Investigation['recommended_action']>,
  string
> = {
  request_quantity_credit: 'Request a quantity credit',
  hold_for_price_review: 'Hold for price review',
  escalate_product_identity: 'Escalate product identity',
  request_supplier_clarification: 'Request supplier clarification',
  inconclusive: 'Inconclusive',
}

export function InvestigationPanel({
  caseId,
  reconciliation,
}: {
  caseId: string
  reconciliation: Reconciliation | null
}) {
  const queryClient = useQueryClient()
  const canInvestigate =
    reconciliation?.status === 'EXCEPTION' ||
    reconciliation?.status === 'NEEDS_REVIEW'
  const investigationQuery = useQuery({
    queryKey: ['cases', caseId, 'investigation', reconciliation?.id],
    enabled: canInvestigate && reconciliation !== null,
    queryFn: ({ signal }) =>
      getInvestigationForRun(caseId, reconciliation?.id ?? '', signal),
  })
  const investigateMutation = useMutation({
    mutationFn: (mode: 'first' | 'new') =>
      startInvestigation(
        caseId,
        reconciliation?.id ?? '',
        mode === 'new'
          ? { newAttempt: true, idempotencyKey: crypto.randomUUID() }
          : undefined
      ),
    onSuccess: async (result) => {
      queryClient.setQueryData(
        ['cases', caseId, 'investigation', reconciliation?.id],
        result
      )
    },
  })
  const investigation = investigateMutation.data ?? investigationQuery.data

  return (
    <Card>
      <CardHeader>
        <CardTitle>Investigation</CardTitle>
        <CardDescription>
          A read-only check of the stored exception. It cannot approve an
          invoice, change the reconciliation, or start a payment.
        </CardDescription>
      </CardHeader>
      <CardContent className='space-y-4'>
        {reconciliation === null ? (
          <p className='text-sm text-muted-foreground'>
            Run reconciliation before investigating this case.
          </p>
        ) : null}
        {reconciliation && !canInvestigate ? (
          <p className='text-sm text-muted-foreground'>
            This reconciliation matched. There is no exception to investigate.
          </p>
        ) : null}
        {canInvestigate ? (
          <div className='space-y-3'>
            <p className='text-sm text-muted-foreground'>
              The result is labeled as a mock investigation or a live LLM
              investigation. The default server configuration is the mock test
              double and does not call a language model.
            </p>
            {investigation ? (
              <div className='space-y-2'>
                <Button
                  variant='outline'
                  onClick={() => investigateMutation.mutate('new')}
                  disabled={investigateMutation.isPending}
                >
                  {investigateMutation.isPending
                    ? 'Starting attempt…'
                    : 'Start another attempt'}
                </Button>
                <p className='text-sm text-muted-foreground'>
                  This stores a new attempt and leaves earlier investigations
                  unchanged. It does not turn live mode on. A server that is
                  already in live mode would send another model request.
                </p>
              </div>
            ) : (
              <Button
                onClick={() => investigateMutation.mutate('first')}
                disabled={
                  investigateMutation.isPending || investigationQuery.isPending
                }
              >
                {investigateMutation.isPending
                  ? 'Investigating…'
                  : 'Investigate exception'}
              </Button>
            )}
            {investigateMutation.isError ? (
              <p className='text-sm text-destructive' role='alert'>
                {investigateMutation.error.message}
              </p>
            ) : null}
            {investigationQuery.isError ? (
              <p className='text-sm text-destructive' role='alert'>
                {investigationQuery.error.message}
              </p>
            ) : null}
            {investigation ? (
              <InvestigationResult investigation={investigation} />
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

function EvidenceNotes({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) {
    return null
  }
  return (
    <div className='space-y-1'>
      <h2 className='text-sm font-medium'>{title}</h2>
      <ul className='list-disc space-y-1 ps-5 text-sm'>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  )
}

function InvestigationResult({
  investigation,
}: {
  investigation: Investigation
}) {
  return (
    <div className='space-y-4'>
      {investigation.mock_execution ? (
        <Alert>
          <AlertTitle>Mock investigation</AlertTitle>
          <AlertDescription>
            This is not live AI reasoning. No language model was called. Tool
            choices come from a deterministic test double. Recorded usage is
            zero because there is nothing to bill.
          </AlertDescription>
        </Alert>
      ) : (
        <Alert>
          <AlertTitle>Live LLM investigation</AlertTitle>
          <AlertDescription>
            Model {investigation.model_name}. Status {investigation.status}.
            Review the evidence before acting. This run cannot approve payment.
            The USD figure is a price-table estimate, not a provider invoice.
          </AlertDescription>
        </Alert>
      )}
      <div className='flex flex-wrap items-center gap-2 text-sm'>
        <Badge variant='outline'>{investigation.status}</Badge>
        {investigation.recommended_action ? (
          <Badge>{actionLabels[investigation.recommended_action]}</Badge>
        ) : null}
        <Badge variant='secondary'>Human review required</Badge>
        <Badge variant='outline'>Attempt {investigation.attempt}</Badge>
        <Badge
          variant={investigation.evidence_validated ? 'default' : 'outline'}
        >
          {investigation.evidence_validated
            ? 'Evidence validated'
            : 'Evidence incomplete'}
        </Badge>
        {investigation.replayed ? (
          <span className='text-muted-foreground'>
            Existing investigation returned unchanged
          </span>
        ) : null}
      </div>
      {investigation.summary ? (
        <p className='text-sm'>{investigation.summary}</p>
      ) : null}
      <EvidenceNotes
        title='Observed facts'
        items={investigation.observed_facts}
      />
      <EvidenceNotes
        title='Possible explanations'
        items={investigation.possible_explanations}
      />
      <EvidenceNotes
        title='Missing evidence'
        items={investigation.missing_evidence}
      />
      <EvidenceNotes
        title='Recommended next actions'
        items={investigation.next_actions}
      />
      {investigation.error_detail ? (
        <p className='text-sm text-destructive' role='alert'>
          {investigation.error_detail}
        </p>
      ) : null}
      {investigation.unresolved_issues.length > 0 ? (
        <div className='space-y-1'>
          <h2 className='text-sm font-medium'>Unresolved</h2>
          <ul className='list-disc space-y-1 ps-5 text-sm'>
            {investigation.unresolved_issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {investigation.findings.length > 0 ? (
        <div className='space-y-2'>
          <h2 className='text-sm font-medium'>Structured findings</h2>
          {investigation.findings.map((finding) => (
            <div key={finding.code} className='rounded-md border p-3 text-sm'>
              <p className='font-medium'>{finding.code}</p>
              <p>{finding.summary}</p>
            </div>
          ))}
        </div>
      ) : null}
      {investigation.citations.length > 0 ? (
        <div className='space-y-2'>
          <h2 className='text-sm font-medium'>Policy citations</h2>
          <p className='text-xs text-muted-foreground'>
            Quoted from the retrieved section. Policy text is evidence, not an
            instruction to the application. Retrieval is lexical, not semantic.
          </p>
          {investigation.citations.map((citation) => (
            <div
              key={citation.section_code}
              className='space-y-1 rounded-md border p-3 text-sm'
            >
              <p className='font-medium'>
                {citation.section_code} · version {citation.version}
              </p>
              <p>{citation.heading}</p>
              <p className='text-muted-foreground'>{citation.excerpt}</p>
            </div>
          ))}
        </div>
      ) : null}
      {investigation.evidence.length > 0 ? (
        <div className='space-y-1'>
          <h2 className='text-sm font-medium'>Evidence retrieved</h2>
          <ul className='list-disc space-y-1 ps-5 text-sm'>
            {investigation.evidence.map((item) => (
              <li key={item.label}>
                {item.label}{' '}
                <span className='text-muted-foreground'>
                  ({item.tool_name})
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className='space-y-2'>
        <h2 className='text-sm font-medium'>Tool execution</h2>
        <ol className='space-y-2 text-sm'>
          {investigation.events.map((event) => (
            <li key={event.ordinal}>
              <span className='text-muted-foreground'>{event.ordinal}. </span>
              {event.tool_name ? `${event.tool_name}: ` : ''}
              {event.summary}
            </li>
          ))}
        </ol>
      </div>
      {investigation.mock_execution ? (
        <p className='text-xs text-muted-foreground'>
          Mock investigation. Provider {investigation.provider}. Test double{' '}
          {investigation.model_name}. Recorded usage:{' '}
          {investigation.input_tokens} input tokens,{' '}
          {investigation.output_tokens} output tokens, estimated cost{' '}
          {investigation.estimated_cost_usd} USD.
        </p>
      ) : (
        <dl className='grid gap-2 text-sm sm:grid-cols-2'>
          <div>
            <dt className='text-muted-foreground'>Execution</dt>
            <dd>Live LLM investigation</dd>
          </div>
          <div>
            <dt className='text-muted-foreground'>Model</dt>
            <dd>{investigation.model_name}</dd>
          </div>
          <div>
            <dt className='text-muted-foreground'>Status</dt>
            <dd>{investigation.status}</dd>
          </div>
          <div>
            <dt className='text-muted-foreground'>Input tokens</dt>
            <dd>{investigation.input_tokens}</dd>
          </div>
          <div>
            <dt className='text-muted-foreground'>Output tokens</dt>
            <dd>{investigation.output_tokens}</dd>
          </div>
          <div>
            <dt className='text-muted-foreground'>Estimated cost</dt>
            <dd>{investigation.estimated_cost_usd} USD</dd>
          </div>
        </dl>
      )}
    </div>
  )
}
