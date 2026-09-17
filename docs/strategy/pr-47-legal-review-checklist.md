# PR #47 Technical Review & Legal Action Checklist

## Summary

PR #47 (`licensing/polyform-noncommercial-1.0.0`) proposes transitioning ZapTrace project-authored code from MIT to PolyForm Noncommercial 1.0.0, alongside contributor licensing guidelines and commercial licensing documentation.

This document records technical findings and provides an explicit legal review checklist for maintainers before merging PR #47.

---

## Technical Audit Findings

1. **Internal Contradiction between CLA.md and CONTRIBUTOR-LICENSING.md**:
   - `CLA.md` explicitly notes: *"This template is intended for legal review before it is relied on operationally."*
   - `CONTRIBUTOR-LICENSING.md` stated that non-trivial contributions require a reviewed CLA on record.
   - **Resolution Required**: Contributor policy must state that during the transition/evaluation period, DCO sign-off applies until qualified legal counsel approves and operationally adopts `CLA.md`.

2. **REUSE & SPDX Compliance**:
   - `LICENSES/PolyForm-Noncommercial-1.0.0.txt` added to repository.
   - REUSE configuration (`REUSE.toml`) updated on PR branch.
   - `pyproject.toml` classifier must be verified against PyPI supported license classifiers.

3. **Packaging Metadata**:
   - OSI-approved "License :: OSI Approved :: MIT License" classifier must be removed if PolyForm is adopted.

---

## Actionable Legal Review Checklist (Human / Counsel Action)

- [ ] **License Selection**: Confirm PolyForm Noncommercial 1.0.0 satisfies project strategic goals.
- [ ] **CLA Adoption**: Review `CLA.md` terms for copyright license grant, patent grants, and re-licensing rights.
- [ ] **DCO Interaction**: Confirm Developer Certificate of Origin (DCO) sign-off policy interaction with CLA.
- [ ] **Commercial Terms**: Review `COMMERCIAL-LICENSING.md` for grant of commercial rights and dual-licensing structure.
- [ ] **Existing Contributor Rights**: Confirm prior MIT contributions are properly identified and handled.

---

## Technical Readiness Status

- Technical changes on PR branch: **Ready for Legal Review**
- CI & REUSE policy gates on PR branch: **Green**
- Merge Decision: **Requires Qualified Legal Approval (Do Not Auto-Merge)**
