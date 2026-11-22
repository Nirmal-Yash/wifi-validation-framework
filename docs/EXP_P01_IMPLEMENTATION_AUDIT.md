# EXP-P01 — Design system and application shell audit

## Baseline

- Repository: `Nirmal-Yash/wifi-validation-framework`
- Starting main commit: `6463ac206ba45dfb219bc081f7fc909d7dfd860c`
- P00 prerequisite: repository baseline and architecture documentation are present.
- P01 status at audit: existing shared shell and theme foundation present; global search, shell-level provider state and permission-filtered global navigation required completion.

## Existing implementation retained

- React 19 + Vite and the existing Tauri/Flask application shell.
- Existing Sidebar/AppShell and all routed pages.
- Existing per-user Organization/Project/Lab workspace context.
- Existing semantic light/dark tokens and reusable UI primitives.
- Existing session/authentication and server-side RBAC boundaries.

## Work completed in P01

- Added an accessible global command search for existing permission-visible modules and the Organization/Project/Lab entries already loaded by the shared workspace context. It supports Ctrl/Cmd+K, result filtering, arrow navigation, Enter, Escape and focus restoration. It does not create a parallel resource API or search data the session is not already authorized to see.
- Added a shell provider-state indicator. It reads only the saved GNS3 Lab binding metadata through the existing read-only API. A configured binding is explicitly labelled `health unknown`; it is not a provider reachability probe. Non-GNS3 providers remain unknown; restricted provider details are not displayed.
- Changed navigation filtering to use the canonical frontend route-permission map, so the search and sidebar share the same visibility decisions. The server remains authoritative.
- Changed the global font tokens to Roboto/Roboto Flex-first and JetBrains Mono-first system font stacks. No remote font, binary font asset or new runtime dependency is introduced.
- Removed the green styling from the static LOCAL MODE label so it cannot be confused with provider or service health.
- Expanded shell component tests and updated the existing frontend design contract.

## Acceptance mapping

| P01 requirement | Implementation/evidence |
|---|---|
| Persistent left navigation | Existing Sidebar/AppShell preserved |
| Organization/Project/Lab selectors | Existing WorkspaceProvider selectors preserved |
| Global search | `GlobalSearch`; module and visible workspace navigation only |
| Provider connectivity indicator | Provider binding status, with health unknown unless an actual probe exists |
| User profile and permissions | Existing UserMenu and canonical `canAccessRoute` filter |
| Main content and loading/error states | Existing shell and reusable UI states preserved |
| Canonical design tokens | `frontend/src/styles/tokens.css` |
| Responsive application shell | Existing responsive product-shell CSS extended for search/provider state |
| Component tests | `frontend/src/test/layout.test.jsx` |
| Existing page/authorization preservation | Existing routes and API guards unchanged |

## Qualification boundary

The source changes and focused tests are prepared. Hosted PR CI and manual viewport/assistive-technology review must pass before P01 is accepted. Do not label the provider connected from binding metadata.
