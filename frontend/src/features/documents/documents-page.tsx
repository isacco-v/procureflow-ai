import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { listDocuments, uploadDocument } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
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

export function DocumentsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const documentsQuery = useQuery({
    queryKey: ['documents'],
    queryFn: ({ signal }) => listDocuments(signal),
  })
  const uploadMutation = useMutation({
    mutationFn: uploadDocument,
    onSuccess: async (document) => {
      await queryClient.invalidateQueries({ queryKey: ['documents'] })
      await navigate({
        to: '/documents/$documentId',
        params: { documentId: document.id },
      })
    },
  })

  return (
    <>
      <Header>
        <Search className='me-auto' />
        <ThemeSwitch />
        <ConfigDrawer />
      </Header>
      <Main>
        <div className='mb-6 space-y-2'>
          <h1 className='text-2xl font-bold tracking-tight'>Documents</h1>
          <p className='max-w-3xl text-muted-foreground'>
            Upload a purchase order, delivery note, or supplier invoice PDF. The
            file is classified from its page text. The file name is kept for
            display and is not used to decide the document type. Nothing is
            written into a procurement case until you accept the extraction.
          </p>
        </div>

        <Card className='mb-6'>
          <CardHeader>
            <CardTitle>Upload a PDF</CardTitle>
            <CardDescription>
              PDF files only. The default reader is a mock extractor, a
              deterministic test double. It is not a language model. OCR is not
              implemented. On the seeded database, accepting PO-B-100, DN-B-100,
              or INV-B-100 is refused so those records stay unchanged. The full
              upload demonstration uses a separate database.
            </CardDescription>
          </CardHeader>
          <CardContent className='space-y-3'>
            <input
              type='file'
              accept='application/pdf,.pdf'
              aria-label='PDF file'
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) {
                  uploadMutation.mutate(file)
                }
                event.target.value = ''
              }}
              disabled={uploadMutation.isPending}
            />
            {uploadMutation.isPending ? (
              <p className='text-sm text-muted-foreground'>Reading the PDF…</p>
            ) : null}
            {uploadMutation.isError ? (
              <p className='text-sm text-destructive' role='alert'>
                {uploadMutation.error.message}
              </p>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Uploaded documents</CardTitle>
            <CardDescription>
              Seeded demonstration cases are separate. An upload stays in review
              until it is accepted.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {documentsQuery.isPending ? (
              <p className='text-sm text-muted-foreground'>
                Loading documents…
              </p>
            ) : null}
            {documentsQuery.isError ? (
              <p className='text-sm text-destructive' role='alert'>
                {documentsQuery.error.message}
              </p>
            ) : null}
            {documentsQuery.data && documentsQuery.data.length === 0 ? (
              <p className='text-sm text-muted-foreground'>
                No PDFs have been uploaded.
              </p>
            ) : null}
            {documentsQuery.data && documentsQuery.data.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>File name</TableHead>
                    <TableHead>Read as</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Extractor</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {documentsQuery.data.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell className='font-medium'>
                        <Link
                          to='/documents/$documentId'
                          params={{ documentId: item.id }}
                          className='underline-offset-4 hover:underline'
                        >
                          {item.original_filename}
                        </Link>
                      </TableCell>
                      <TableCell>
                        {item.document_number
                          ? `${labelType(item.document_type)} ${item.document_number}`
                          : labelType(item.document_type)}
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={item.status} />
                      </TableCell>
                      <TableCell>
                        <ExtractorBadge mocked={item.mocked} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : null}
          </CardContent>
        </Card>
      </Main>
    </>
  )
}

export function labelType(value: string | null) {
  if (value === 'purchase_order') return 'Purchase order'
  if (value === 'delivery_note') return 'Delivery note'
  if (value === 'invoice') return 'Invoice'
  return 'Unclassified'
}

export function StatusBadge({
  status,
}: {
  status: 'needs_review' | 'accepted' | 'failed'
}) {
  const label =
    status === 'needs_review'
      ? 'Needs review'
      : status === 'accepted'
        ? 'Accepted'
        : 'Failed'
  return <Badge variant='outline'>{label}</Badge>
}

export function ExtractorBadge({ mocked }: { mocked: boolean | null }) {
  if (mocked === true) return <Badge variant='outline'>Mock extraction</Badge>
  if (mocked === false)
    return <Badge variant='outline'>Live LLM extraction</Badge>
  return <Badge variant='outline'>Not extracted</Badge>
}
