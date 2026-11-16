import { createFileRoute } from '@tanstack/react-router'
import { CaseDetailPage } from '@/features/cases/case-detail-page'

export const Route = createFileRoute('/_authenticated/cases/$caseId')({
  component: CaseDetailPage,
})
