# Stats Perform Stark Web App Stack

Use the Opta Stark Nx/Next.js archetype for web-app targets.

Operational guidance:

- Use Nx and Next.js conventions from the Stark template.
- Keep `/livez` and `/readyz` health checks for web-app delivery.
- Use Stark Docker and standalone output conventions.
- Use Jest and Testing Library for frontend tests unless the target repository already standardizes otherwise.
- Follow Stark web observability and structured logging conventions when relevant.

Implied stacks:

- `statsperform-playbook` is implied because Stark uses `@statsperform/react-playbook`.

Boundaries:

- This stack applies only to web-app targets.
- This stack does not imply MSA and is not a backend service deployment model.
