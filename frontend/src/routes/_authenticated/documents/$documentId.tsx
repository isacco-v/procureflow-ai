import { createFileRoute } from '@tanstack/react-router'
import { DocumentDetailPage } from '@/features/documents/document-detail-page'

export const Route = createFileRoute('/_authenticated/documents/$documentId')({
  component: DocumentDetailPage,
})
