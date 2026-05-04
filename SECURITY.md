# Security Policy

## Scope

MxAnonymizer processes personal data as part of database anonymization. Security
issues include — but are not limited to:

- Patterns that allow PII to survive anonymization (leak bypass)
- Determinism weaknesses that allow reverse-engineering original values from
  anonymized output
- Dependency vulnerabilities in the published package
- Privilege escalation in the database connection handling

## Reporting a vulnerability

Please **do not** file a public GitHub issue for security vulnerabilities.

Report privately via GitHub's "Report a vulnerability" button on the
**Security** tab of this repository. If you cannot use that, contact the
maintainers directly (see the project's GitHub profile for details).

Include in your report:
- A description of the vulnerability
- Steps to reproduce
- Impact assessment: what data could be exposed, and under what conditions

We aim to:
- Acknowledge reports within **5 business days**
- Provide a fix or mitigation plan within **30 days** for confirmed issues

## Supported versions

Only the latest released version receives security patches. Patch releases
are issued promptly for confirmed security issues.
