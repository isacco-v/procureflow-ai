import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { listCases, seedSyntheticCases } from '@/lib/api'
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
import { StatusBadge } from './status-badge'

export function CasesPage() {
  const queryClient = useQueryClient()
  const casesQuery = useQuery({
    queryKey: ['cases'],
    queryFn: ({ signal }) => listCases(signal),
  })
  const seedMutation = useMutation({
    mutationFn: seedSyntheticCases,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['cases'] })
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
          <h1 className='text-2xl font-bold tracking-tight'>
            Procurement cases
          </h1>
          <p className='max-w-3xl text-muted-foreground'>
            Seeded scenarios and cases created from accepted PDF uploads.
            Reconciliation compares stored lines with deterministic arithmetic.
            Exception and needs-review cases can be opened for a read-only
            investigation.
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Stored cases</CardTitle>
            <CardDescription>
              Synthetic seed rows and uploaded rows stay distinct. The same
              stored lines produce the same reconciliation result.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {casesQuery.isPending ? (
              <p className='text-sm text-muted-foreground'>Loading cases…</p>
            ) : null}
            {casesQuery.isError ? (
              <p className='text-sm text-destructive' role='alert'>
                {casesQuery.error.message}
              </p>
            ) : null}
            {casesQuery.data && casesQuery.data.length === 0 ? (
              <div className='space-y-3'>
                <p className='text-sm text-muted-foreground'>
                  No cases are stored yet. Load the five synthetic scenarios to
                  inspect them.
                </p>
                <Button
                  onClick={() => seedMutation.mutate()}
                  disabled={seedMutation.isPending}
                >
                  {seedMutation.isPending
                    ? 'Loading synthetic cases…'
                    : 'Load synthetic cases'}
                </Button>
                {seedMutation.isError ? (
                  <p className='text-sm text-destructive' role='alert'>
                    {seedMutation.error.message}
                  </p>
                ) : null}
              </div>
            ) : null}
            {casesQuery.data && casesQuery.data.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Reference</TableHead>
                    <TableHead>Case</TableHead>
                    <TableHead>Supplier</TableHead>
                    <TableHead>Data</TableHead>
                    <TableHead>Latest reconciliation</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {casesQuery.data.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell className='font-medium'>
                        <Link
                          to='/cases/$caseId'
                          params={{ caseId: item.id }}
                          className='underline-offset-4 hover:underline'
                        >
                          {item.reference}
                        </Link>
                      </TableCell>
                      <TableCell>{item.title}</TableCell>
                      <TableCell>{item.supplier.name}</TableCell>
                      <TableCell>
                        <Badge variant='outline'>
                          {item.origin === 'upload'
                            ? 'Uploaded'
                            : 'Synthetic seed'}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {item.latest_reconciliation_status ? (
                          <StatusBadge
                            status={item.latest_reconciliation_status}
                          />
                        ) : (
                          <span className='text-muted-foreground'>Not run</span>
                        )}
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
