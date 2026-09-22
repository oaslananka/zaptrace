# OpenSSF BadgeApp Proposal Links

OpenSSF BadgeApp supports proposal links that pre-fill criterion status and justification fields. Use these links only after verifying the evidence in the repository.

## Project

- BadgeApp project: `https://www.bestpractices.dev/en/projects/13403`
- Repository: `https://github.com/oaslananka/zaptrace`

## Workflow

1. Open the BadgeApp project.
2. Submit often to save progress.
3. For each criterion, use `docs/openssf-evidence.md` as the evidence source.
4. Mark criteria as `Met` only when repository evidence is public and current.
5. Mark solo-maintainer blockers as `Unmet` or justify as partial where the criterion permits.
6. Do not mark Gold-only human review or bus-factor criteria as met until independent contributors exist.

## Example proposal URL pattern

```text
https://www.bestpractices.dev/en/projects/13403/choose/edit?CRITERION_ID_status=Met&CRITERION_ID_justification=URL_ENCODED_JUSTIFICATION
```

## Suggested justifications

| Criterion | Suggested evidence |
|-----------|--------------------|
| Project description | `README.md` describes ZapTrace, quickstart, status, limitations, and non-claims. |
| Contribution process | `CONTRIBUTING.md` and `.github/PULL_REQUEST_TEMPLATE.md`. |
| License | `LICENSE`, MIT. |
| Documentation basics | `README.md`, docs site, `docs/tutorials/getting-started.md`. |
| Governance | `GOVERNANCE.md`. |
| Roles | `MAINTAINERS.md`. |
| Security policy | `SECURITY.md`. |
| Roadmap | `ROADMAP.md` and `docs/ROADMAP.md`. |
| Architecture | `docs/ARCHITECTURE.md` and `docs/explanation/architecture.md`. |
| Release notes | `CHANGELOG.md` and GitHub Releases. |
| Gold bus factor | Do not mark met until at least two active maintainers/contributors are demonstrated. |
