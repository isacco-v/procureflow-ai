import { ClipboardList, FileText, LayoutDashboard } from 'lucide-react'
import { type SidebarData } from '../types'

export const sidebarData: SidebarData = {
  navGroups: [
    {
      title: 'General',
      items: [
        {
          title: 'Overview',
          url: '/',
          icon: LayoutDashboard,
        },
        {
          title: 'Cases',
          url: '/cases',
          icon: ClipboardList,
        },
        {
          title: 'Documents',
          url: '/documents',
          icon: FileText,
        },
      ],
    },
  ],
}
