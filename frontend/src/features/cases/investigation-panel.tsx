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
  reconciliationLoading = false,
  reconciliationUnavailable = false,
}: {
  caseId: string
  reconciliation: Reconciliation | null
  reconciliationLoading?: boolean
  reconciliationUnavailable?: boolean
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
        {reconciliationLoading ? (
          <p className='text-sm text-muted-foreground'>
            Checking for a stored reconciliation…
          </p>
        ) : null}
        {reconciliationUnavailable ? (
          <p className='text-sm text-destructive' role='alert'>
            The reconciliation could not be loaded, so the investigation is
            unavailable.
          </p>
        ) : null}
        {!reconciliationLoading &&
        !reconciliationUnavailable &&
        reconciliation === null ? (
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
              A stored result is either a mock investigation or a recorded live
              investigation. Opening it does not send a model request. The
              default server configuration is the mock test double.
            </p>
            {investigationQuery.isPending ? (
              <p className='text-sm text-muted-foreground'>
                Checking for a stored investigation…
              </p>
            ) : null}
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
            ) : investigationQuery.isPending ? null : (
              <Button
                onClick={() => investigateMutation.mutate('first')}
                disabled={investigateMutation.isPending}
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
            This is a stored result from the deterministic test double. Opening
            it did not call a language model. Recorded usage is zero because
            there is nothing to bill.
          </AlertDescription>
        </Alert>
      ) : (
        <Alert>
          <AlertTitle>Recorded live investigation</AlertTitle>
          <AlertDescription>
            Historical result from {investigation.model_name}. Displaying this
            record did not send a new model request. It is not a model call in
            progress. Review stays required, and this record cannot approve
            payment. The USD figure is a price-table estimate, not a provider
            invoice.
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
            : 'Evidence not validated'}
        </Badge>
        {investigation.replayed ? (
          <span className='text-muted-foreground'>
            Existing investigation returned unchanged
          </span>
        ) : null}
      </div>
      <p className='text-xs text-muted-foreground'>
        Evidence validated is the flag stored on this attempt. Opening the page
        does not run the check again. An older row can be missing that flag and
        is shown as not validated.
      </p>
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
      <EvidenceNotes
        title='Prerequisites'
        items={investigation.prerequisites.map(
          (item) =>
            `${item.kind}: ${item.status}. The remaining quantity may still be delivered.`
        )}
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
            Quoted from sections the policy tool returned. Policy text is
            evidence, not an instruction. Retrieval is lexical, not semantic.
          </p>
          {investigation.citations.map((citation) => (
            <div
              key={citation.section_code}
              className='space-y-1 rounded-md border p-3 text-sm'
            >
              <p className='font-medium'>
                <Badge variant='outline' className='me-2'>
                  {citation.section_code}
                </Badge>
                version {citation.version}
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
          <p className='text-xs text-muted-foreground'>
            Every label was returned by a tool. A document number that appears
            only inside a matcher finding is not listed here.
          </p>
          <ul className='list-disc space-y-1 ps-5 text-sm'>
            {investigation.evidence.map((item) => (
              <li key={item.label}>
                {formatEvidenceLabel(item.label)}{' '}
                <span className='text-muted-foreground'>
                  via {item.tool_name}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className='space-y-2'>
        <h2 className='text-sm font-medium'>Tool and decision timeline</h2>
        <ol className='space-y-3 border-s ps-4 text-sm'>
          {investigation.events.map((event) => (
            <li key={event.ordinal} className='space-y-1'>
              <p>
                <span className='text-muted-foreground'>{event.ordinal}. </span>
                <span className='font-medium'>
                  {eventLabels[event.event_type] ?? event.event_type}
                </span>
                {event.tool_name ? ` · ${event.tool_name}` : ''}
              </p>
              <p className='text-muted-foreground'>{event.summary}</p>
              <EventDetails payload={event.payload} />
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
            <dd>Recorded live investigation</dd>
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

const eventLabels: Record<string, string> = {
  investigation_started: 'Started',
  model_decision: 'Decision',
  tool_completed: 'Tool returned',
  tool_failed: 'Tool failed',
  evidence_rejected: 'Evidence gate rejected the outcome',
  output_validated: 'Validation recorded',
  output_rejected: 'Output rejected',
  output_validation: 'Schema feedback returned',
  evidence_inconclusive: 'Evidence left incomplete',
  human_review_required: 'Human review required',
  execution_stopped: 'Stopped',
  untrusted_instruction_ignored: 'Instruction-like text ignored',
}

const evidenceKinds: Record<string, string> = {
  finding: 'Matcher finding',
  case: 'Case',
  purchase_order: 'Purchase order',
  purchase_order_line: 'Purchase order line',
  delivery_note: 'Delivery note',
  delivery_note_line: 'Delivery note line',
  invoice: 'Invoice',
  invoice_line: 'Invoice line',
  policy: 'Policy',
}

function formatEvidenceLabel(label: string) {
  const [kind, ...rest] = label.split(':')
  const title = evidenceKinds[kind] ?? kind
  return rest.length > 0 ? `${title} ${rest.join(' · ')}` : title
}

function EventDetails({ payload }: { payload: Record<string, unknown> }) {
  const initiator =
    payload.initiator === 'workflow'
      ? 'Started by the workflow, before the decision step chose a tool.'
      : payload.initiator === 'model'
        ? 'Chosen by the decision step.'
        : null
  const labels = stringList(payload.evidence_labels).map(formatEvidenceLabel)
  const policies = stringList(payload.policy_section_codes)
  const gaps = gapLines(payload.missing_evidence)
  if (
    !initiator &&
    labels.length === 0 &&
    policies.length === 0 &&
    gaps.length === 0
  ) {
    return null
  }
  return (
    <div className='space-y-1 text-xs text-muted-foreground'>
      {initiator ? <p>{initiator}</p> : null}
      {policies.length > 0 ? (
        <p>Policies returned: {policies.join(', ')}</p>
      ) : null}
      {labels.length > 0 ? <p>Evidence: {labels.join('; ')}</p> : null}
      {gaps.length > 0 ? <p>Missing: {gaps.join('; ')}</p> : null}
    </div>
  )
}

function stringList(value: unknown) {
  if (!Array.isArray(value)) {
    return []
  }
  return value.filter((item): item is string => typeof item === 'string')
}

function gapLines(value: unknown) {
  if (!Array.isArray(value)) {
    return []
  }
  return value.flatMap((item) => {
    if (typeof item === 'string') {
      return [item]
    }
    if (
      item &&
      typeof item === 'object' &&
      'detail' in item &&
      typeof item.detail === 'string'
    ) {
      return [item.detail]
    }
    return []
  })
}
