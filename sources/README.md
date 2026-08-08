# Workspace Source Roots

Put implementation repositories for this Echelon workspace here.

Examples:

```bash
git clone git@github.com:example/app.git sources/app
git clone git@github.com:example/api.git sources/api
```

After adding sources, declare them in `.echelon/config.yml`:

```yaml
sources:
  - id: app
    path: sources/app
```

Child repositories under this directory are ignored by workspace Git; this README is tracked so the location is visible in new workspaces.
