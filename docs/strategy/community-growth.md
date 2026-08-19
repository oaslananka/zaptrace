# Community Growth Strategy

> **Status:** Draft
> **Owner:** Core team
> **Last updated:** 2026-06-09
> **Configuration note (2026-07-27):** This is a historical growth plan, not a list of currently enabled support channels. GitHub Issues is the active public channel; Discussions remains a future option.

---

## 1. Why Community Matters for an EDA Tool

Open-source EDA tools live or die by their communities. KiCad succeeded because users contributed
libraries, tutorials, and translations. ZapTrace must build similarly — but faster, by leveraging
modern platforms.

**Key insight:** ZapTrace's primary users are not traditional EE engineers first. They are
**software engineers building hardware** — ML engineers, firmware developers, hardware startups,
hobbyists. This shapes where and how we grow.

---

## 2. Target Audiences

| Segment | Size | Pain Point | ZapTrace Fit |
|---------|------|------------|--------------|
| ML/AI hardware engineers | Medium | Need quick PCB for inference boards | Code-first, fast iteration |
| Firmware engineers | Large | KiCad GUI is slow, want CLI | YAML in, Gerber out |
| Hardware startups | Small | Need fast prototype-to-manufacturing | Autopilot + pipeline |
| EDA researchers | Niche | Want programmable routing engine | Python API, pluggable |
| Hobbyists / makers | Very large | KiCad learning curve too steep | `zaptrace quickstart` |
| Students | Large | Need free, scriptable EDA for projects | pip install, docs |

---

## 3. Growth Channels

### 3.1 Content (Top of Funnel)

| Channel | Content Type | Frequency | Owner |
|---------|-------------|-----------|-------|
| Blog | Tutorials, case studies, release notes | Bi-weekly | Core team |
| YouTube | Walkthroughs, "PCB in 5 min" | Monthly | Community |
| Twitter/X | Snippet showcases, GIF demos | 3× / week | Core team |
| Hacker News | Launch posts, technical deep-dives | Launch & milestones | Core team |
| Reddit r/PrintedCircuitBoard | Help threads, "Built with ZapTrace" | Weekly | Community |

**Priority:** Blog posts with runnable `.yaml` examples. Each post should produce a real PCB.

### 3.2 Community Platforms

| Platform | Purpose | Moderation |
|----------|---------|------------|
| GitHub Issues (current) / Discussions (planned) | Q&A, feature requests, show & tell | Core team |
| Discord | Real-time help, community bonding | Core + power users |
| Stack Overflow | SEO-friendly Q&A (zaptrace tag) | Core team |

### 3.3 Contribution Paths

| Role | Path | Incentive |
|------|------|-----------|
| Bug reporter | File good bug → get `contributor` badge | Recognition |
| Documentation | Fix typo → write guide → own a section | Maintainer track |
| Component library | Add footprints → curate a category | Credit in README |
| Plugin author | Write plugin → publish → get listed | Directory listing |
| Core contributor | 5 PRs → commit access | Team membership |

### 3.4 Badges & Recognition

GitHub-native recognition system:

- `🏆 Top Contributor` — quarterly, based on merged PRs
- `📦 Library Curator` — maintains component library category
- `🔧 Plugin Author` — published a plugin
- `📖 Doc Knight` — significant documentation contributions
- `🐛 Bug Hunter` — 5+ accepted bug reports with reproduction

---

## 4. Launch Strategy

### Pre-Launch (Now → v0.2.0)

1. Set up GitHub Discussions as primary Q&A
2. Create Discord server (invite in README)
3. Publish 3 "getting started" blog posts
4. Seed Stack Overflow with 5 answered Q&A pairs
5. Reach out to 10 EE/hardware YouTubers for preview access

### Launch (v0.2.0)

1. Hacker News "Show HN" with live demos
2. Reddit posts on r/PrintedCircuitBoard, r/embedded, r/electronics
3. Twitter/X thread with GIF demos of each feature
4. Blog: "Why we built ZapTrace"
5. Reach out to Hackaday, cnx-software, electronics-lab

### Post-Launch (v0.2.0 → v0.3.0)

1. Monthly release cadence
2. Community highlight: showcase one community design per week
3. Plugin contest: best plugin wins hardware prize
4. Office hours: bi-weekly Discord AMA with core team

---

## 5. Metrics

| Metric | Baseline | 3-month Target | 6-month Target |
|--------|----------|----------------|----------------|
| GitHub stars | 0 | 500 | 2,000 |
| Discord members | — | 200 | 1,000 |
| Monthly PyPI downloads | — | 1,000 | 10,000 |
| Contributors (non-core) | 0 | 10 | 50 |
| Community plugins | 0 | 5 | 25 |
| Stack Overflow questions | 0 | 20 | 100 |
| Blog subscribers | 0 | 100 | 500 |

---

## 6. Governance Model

### Phase 1: BDFL (v0.1–v0.3)

Core team makes all decisions. Community input currently arrives through GitHub Issues; Discussions may be enabled later.

### Phase 2: Steering Committee (v0.4+)

5-member committee: 2 core + 2 community + 1 independent.

Decision areas:
- RFC approval
- Plugin ecosystem standards
- Release management
- Code of Conduct enforcement

---

## 7. Code of Conduct Enforcement

See `CODE_OF_CONDUCT.md`. Key points:
- All community spaces (Discord, GitHub, Stack Overflow) are covered
- Reports to `conduct@zaptrace.dev`
- Response within 48 hours
- Confidential by default

---

## 8. Immediate Next Steps

- [ ] Create GitHub Discussions (enable on repo settings)
- [ ] Create Discord server, link from README
- [ ] Draft 3 blog posts: "Quickstart", "Autopilot", "Export to JLCPCB"
- [ ] Answer 5 Stack Overflow questions preemptively
- [ ] Contact 3 YouTubers for preview
- [ ] Set up community metrics dashboard
