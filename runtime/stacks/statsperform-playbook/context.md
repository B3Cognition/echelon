# Stats Perform Playbook Stack

Use Playbook for UI components, design tokens, icons, forms, accessibility-minded composition, and design-system compliance on web-app targets.

Operational guidance:

- Use `npx -y @statsperform/playbook-cli` for component lookup, patterns, tokens, icons, form-builder guidance, examples, and compliance checks.
- Prefer Playbook components and tokens when they cover the requested UI behavior.
- Use Playbook Form Builder for forms unless requirements explicitly choose another form approach.
- Add accessibility-oriented UI tests around composed Playbook interfaces.
- Run Playbook compliance checks before UI sign-off when implementation source exists.

Boundaries:

- This stack does not imply Stark.
- This stack does not choose the frontend framework, workspace manager, or frontend test runner.
