import { createFileRoute } from '@tanstack/react-router'
import { AuthenticatedLayout } from '@/components/layout/authenticated-layout'

// Application shell inherited from the admin template.
// The pathless route does not authenticate a user. Authentication is planned.
export const Route = createFileRoute('/_authenticated')({
  component: AuthenticatedLayout,
})
