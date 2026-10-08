# Advising and Early College coverage

The existing RSS feeds remain in place. Bounded public HTML monitors add NACADA
Academic Advising Today, CCRC advising/student-support and dual-enrollment
publication catalogs, MDRC publications, Massachusetts DESE announcements and
Early College resources, Massachusetts DHE releases and Early College resources,
The Mentor, and MassINC Early College research/policy.

The monitor scans article link titles explicitly for proactive advising, case
management, guided pathways, caseloads, early alerts, transfer advising, AI in
advising and advising effectiveness, alongside Early College/dual enrollment.
Only configured article URL patterns and HTTPS hosts are requested. Every
request and redirect checks robots.txt; unavailable robots, denied resources,
login/access failures and unsupported content are reported in feed_errors.
Requests honor crawl delay/request rate with a one-second minimum, a 15-second
timeout, a 2 MB limit and at most six articles per listing. No PDF extraction,
JavaScript execution, credentials or paywall bypass is provided. A page layout,
metadata or access change can reduce coverage; no accessible links/dates is a
visible warning rather than an invented finding.

Topic labels now use word boundaries and article content rather than source
names. Advising requires postsecondary/academic context. Early College has a
distinct label. Substantive priority items receive a 12-point bonus; Massachusetts
Early College receives another 8 points, and reported findings/methods add 6.
Selection reserves an opportunity for one qualifying item from each priority
topic before filling remaining slots by score, while retaining source caps and
story clustering. Reservations require a score of at least 18 and actual
research, practice, policy, partnership or outcome content. Empty categories
remain empty when worthwhile fresh material is unavailable.

Publication dates come from publication metadata, article JSON-LD, a single
article time, or an explicitly labeled visible publication date. Modified dates,
copyright years, missing dates, month-only dates and future dates are not
fresh news. RSS requires a published date, not only an updated timestamp.
Previously briefed canonical URLs are not recycled, including tracking variants.
This deliberately favors omission over accidentally calling old material new;
a genuinely updated release should have a new source URL to be considered.

Older research within 365 days is eligible only for the separate research_context
field/Markdown section when accessible text contains both findings and methods.
It never fills a fresh-topic reservation or a LinkedIn draft. The existing page
uses its established top_signals structure; the added context field is available
in the JSON and Markdown without a homepage design change.

For priority stories, editorial observations quote extracted source sentences
for findings, methods and limitations when present. Missing evidence is stated
explicitly. Practical implications are framed as editorial questions, not
attributed to a study. RSS evidence is limited to its supplied summary; the HTML
monitors use accessible paragraphs with navigation/footer content excluded.
These are conservative extracts, not a complete systematic review; PDFs may
contain evidence unavailable in the landing page.

The only change to the existing publishing workflow is its name and weekday
schedule (Monday/Wednesday/Friday, same UTC time). Deployment steps are retained.
The separate test workflow runs regression tests and a live, read-only source
smoke check on the working branch/pull requests. It does not generate, commit,
publish or deploy a briefing. Live source failures are logged; offline tests
provide deterministic regression checks.

Run tests with:
    python -m unittest discover -s higher-ed-intel/generator -p 'test_*.py' -v

Illustrative examples, not live findings:
* An advising evaluation reports its comparison method, measured persistence
  outcome, caseload or outreach arrangements, and stated limits. The brief
  distinguishes measured results from implementation questions for a college.
* A Massachusetts Early College announcement identifies designated high
  school/college partners, funded seats or credit arrangements, its publication
  date, and the practical support/transfer questions raised by those changes.
