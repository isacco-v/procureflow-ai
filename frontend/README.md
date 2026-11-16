# ProcureFlow AI frontend

React, TypeScript, and Vite shell for ProcureFlow AI. The overview page calls `GET /health` on the local API. It does not upload documents or start a workflow.

## Attribution

This application is derived from [shadcn-admin](https://github.com/satnaing/shadcn-admin) by Sat Naing.

- License: MIT, kept in [LICENSE](LICENSE)
- Copyright: Sat Naing, 2024
- Snapshot: package version 2.2.1, commit `e16c87f213a5ba5e45964e9b67c792105ec74d26`

Sample product pages shipped with that template were removed: analytics dashboard, tasks, apps, chats, users, settings forms, help center, authentication demos, and the Clerk example. The layout, theme controls, error pages, and `src/components/ui` primitives remain so later procurement screens can use them.

## Scripts

```bash
cp .env.example .env
pnpm install
pnpm dev
pnpm build
```

`VITE_API_BASE_URL` defaults to `http://127.0.0.1:8000` when it is unset. Vite reads `.env` from this directory only.

The production check used by CI is `pnpm build` (`tsc -b` and `vite build`). Component tests inherited from the template run in a Playwright browser and are not part of that check.
