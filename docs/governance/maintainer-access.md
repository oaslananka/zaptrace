# Maintainer Access Policy

This policy defines how ZapTrace grants, reviews, and removes access to sensitive project resources.

## Sensitive resources

Sensitive resources include:

- repository administration and branch/ruleset settings;
- secrets, environments, and deployment/release credentials;
- package or container registry publishing rights;
- GitHub private vulnerability reports and advisories;
- GitHub Pages and documentation deployment settings;
- Project board automation with write access.

## Default access rule

New collaborators must receive the lowest practical permission level by default. Escalated access requires documented need, maintainer review, and a clear responsibility.

## Escalation criteria

Before granting write, maintain, admin, release, or secret access, the lead maintainer should review:

- contribution history and technical area;
- security posture, including 2FA/passkey use;
- whether the access is needed for the role;
- whether a narrower permission or temporary access is sufficient;
- whether the access creates bus-factor or conflict-of-interest risk.

## Required maintainer practices

Maintainers with sensitive access must:

- use multi-factor authentication for GitHub;
- avoid sharing tokens, SSH keys, or recovery codes;
- use least-privilege personal access tokens when tokens are necessary;
- report suspected account compromise immediately;
- avoid running untrusted pull request code with privileged credentials.

## Review cadence

Sensitive access should be reviewed when:

- a new release line is created;
- a collaborator changes role or becomes inactive;
- a security incident occurs;
- a new package registry or deployment target is added;
- at least annually if the project has multiple maintainers.

## Removal

Access must be removed promptly when it is no longer needed, when a collaborator becomes inactive for sensitive workflows, or when compromise is suspected.
