import type { MatchStatus } from '@/lib/api'
import { Badge } from '@/components/ui/badge'

const labels: Record<MatchStatus, string> = {
  MATCHED: 'Matched',
  EXCEPTION: 'Exception',
  NEEDS_REVIEW: 'Needs review',
}

export function StatusBadge({ status }: { status: MatchStatus }) {
  const variant =
    status === 'EXCEPTION'
      ? 'destructive'
      : status === 'NEEDS_REVIEW'
        ? 'secondary'
        : 'default'
  return <Badge variant={variant}>{labels[status]}</Badge>
}
