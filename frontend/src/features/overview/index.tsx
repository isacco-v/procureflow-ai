import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { apiBaseUrl, getHealth } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

export function OverviewPage() {
  const healthQuery = useQuery({
    queryKey: ['health'],
    queryFn: ({ signal }) => getHealth(signal),
    retry: false,
  })

  return (
    <>
      <Header>
        <Search className='me-auto' />
        <ThemeSwitch />
        <ConfigDrawer />
      </Header>

      <Main>
        <div className='mb-6 space-y-1'>
          <h1 className='text-2xl font-bold tracking-tight'>ProcureFlow AI</h1>
          <p className='max-w-2xl text-muted-foreground'>
            Procurement cases can be reconciled from stored purchase orders,
            delivery notes, and invoices.{' '}
            <Link
              to='/cases'
              className='font-medium text-foreground underline-offset-4 hover:underline'
            >
              Open procurement cases
            </Link>
            .
          </p>
        </div>

        <div className='grid gap-4 lg:grid-cols-2'>
          <Card>
            <CardHeader>
              <CardTitle>API status</CardTitle>
              <CardDescription>
                Live response from{' '}
                <code className='text-xs'>GET {apiBaseUrl}/health</code>
              </CardDescription>
            </CardHeader>
            <CardContent>
              {healthQuery.isPending ? (
                <p className='text-sm text-muted-foreground'>
                  Checking the API…
                </p>
              ) : null}
              {healthQuery.isError ? (
                <p className='text-sm text-destructive' role='alert'>
                  {healthQuery.error.message}
                </p>
              ) : null}
              {healthQuery.data ? (
                <dl className='grid gap-4 sm:grid-cols-2' aria-live='polite'>
                  <StatusItem label='Status' value={healthQuery.data.status} />
                  <StatusItem
                    label='Service'
                    value={healthQuery.data.service}
                  />
                  <StatusItem
                    label='Environment'
                    value={healthQuery.data.environment}
                  />
                  <div>
                    <dt className='text-sm text-muted-foreground'>AI mode</dt>
                    <dd className='mt-1'>
                      <Badge variant='outline'>
                        {healthQuery.data.ai_mode}
                      </Badge>
                    </dd>
                  </div>
                </dl>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>This version</CardTitle>
              <CardDescription>
                The screen reads the health check and links to synthetic cases.
              </CardDescription>
            </CardHeader>
            <CardContent className='space-y-4 text-sm'>
              <div>
                <h2 className='font-medium'>Available</h2>
                <ul className='mt-1 list-disc space-y-1 ps-5 text-muted-foreground'>
                  <li>Application shell and theme controls</li>
                  <li>Backend liveness check</li>
                  <li>Mock AI mode, with no paid request</li>
                  <li>Synthetic cases and deterministic three-way matching</li>
                </ul>
              </div>
              <div>
                <h2 className='font-medium'>Later iterations</h2>
                <ul className='mt-1 list-disc space-y-1 ps-5 text-muted-foreground'>
                  <li>Document intake and structured extraction</li>
                  <li>Bounded investigation with human review</li>
                </ul>
              </div>
            </CardContent>
          </Card>
        </div>
      </Main>
    </>
  )
}

function StatusItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className='text-sm text-muted-foreground'>{label}</dt>
      <dd className='mt-1 font-medium'>{value}</dd>
    </div>
  )
}
