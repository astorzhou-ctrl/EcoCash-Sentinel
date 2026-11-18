ECOCASH SENTINEL  -  Step 16: the 17 remaining modules (compliance, management systems, resilience, intelligence, platform)
===========================================================================================================================
WHAT IS NEW IN STEP 16  (all 17 remaining modules; see Sentinel_Step16_Modules_Guide.txt)
  - COMPLIANCE & PRIVACY: Obligations Hub (the 24 Appendix II laws + the Data Protection Act, owners, monthly statements; an exception creates an action and, if material, an incident),
    Regulatory Change (closes only when obligations, controls and policies are updated and the owner attests), Privacy & Breach Clock (24-hour POTRAZ and 72-hour data-subject clocks started by
    an incident marked as a personal-data breach, notice templates, DPIAs, processing records, subject requests), Policy Hub (versions, annual review, attestation campaigns, cross-reference checks).
  - MANAGEMENT SYSTEMS: Standards Hub (ISO 27001, 22301 and 42001 side by side: clauses 4-10, 93 + 38 Annex A controls, nonconformities that create actions and lower linked controls, audits,
    management review pack) with ISMS (versioned Statement of Applicability), BCMS and AIMS (AI system inventory with go-live rules) workspaces onto the same records.
  - RESILIENCE: BCM Studio (BIA, plans, exercises that feed recovery and open gap actions), Third-Party Risk (tiering, weighted assessment, concentration, exit plans), Cyber & IT Risk (assets,
    vulnerabilities with patch time limits, alerts, snapshots, scanner import), Crisis Room (declare, notify the team, timeline, playbooks, templates, after-action rule).
  - INTELLIGENCE: Document Intelligence (highlighted passages, draft risks with confidence and register match, decisions logged, duties to Obligations Hub, regulatory change from a document),
    Predictive Analytics (trend forecast with a 90% band, breach probability, anomalies, back-tested accuracy, model register with revalidation, a person confirms before an action).
  - PLATFORM: Workflow Designer (versioned lifecycles approved by a different person, per-state time limits, records keep their version), Integration Hub (connectors, one-time keys, health,
    authenticated inbound feeds for KRI readings, fraud alerts and vulnerabilities), Data & Reports (governed datasets, report builder, watermarked Excel/CSV downloads, schedules by e-mail,
    90-day Deleted items, Power BI dataset feed).
  - FIXED: the server now STARTS the mail scheduler (the Step 15 package did not, so daily reminders would not have run on their own).
  - Not built: PDF/Word/PowerPoint/PNG/SVG report downloads; configuring the risk and action lifecycles; Board routing of High risks. Tested against local stand-ins, not real mail, web or BI services.

WHAT IS NEW IN STEP 15  (see Sentinel_Advanced_Modules_Guide.txt)
  - Strategy Map, Scenario Lab, Emerging Radar, Audit Workspace, Fraud Intelligence and Speak-Up Cases; E-mail reminders (Administration > E-mail: SMTP link, one daily digest per person of their
    overdue and due-soon actions, tasks, audit findings, control retests, and now the new modules' due dates; owner names can be mapped to people); Ask Sentinel searches reliable sources by itself
    for anything outside the system or about the present (Advanced mode), and says so when it cannot reach them.

WHAT IS NEW IN STEP 6  (Weekly KPI grows up)
  - Charts in the weekly report by default: every group shows its charts under its table (trend charts, side-by-side
    comparisons, daily transaction charts), in the same grouping as the Excel report.
  - Charts and PowerPoint tab: choose, for each group, how many charts go on a slide (1, 2 or 4); add, edit, remove and
    re-order charts; pick the chart type (columns, bars, lines, area), what it shows and which indicators; reset a
    group to the standard. Download PowerPoint builds the weekly deck in the style of your July deck (blue accent bar and
    logo, charts in tiles, commentary in the blue box, sources at the foot). The charts are real PowerPoint charts:
    right-click > Edit Data works. Download Excel is unchanged and uses the same grouping and order.
  - Internal figures: type the weekly OTP-fraud and SIM-swap numbers (they also feed their KRIs, so alerts fire), or
    upload the transaction-monitoring export (Date, Product, TS successful, TF failed, TA other): Sentinel calculates the
    weekly success rate per product, compares it with its target, and draws the daily transaction charts.
  - Verified sources (your KPI_LINKS list): 'Load my sites list' brings in the sites as PROPOSALS. Nothing is visited
    until (1) a different person verifies the site, (2) the master switch is ON. Controls: https only, approved host names,
    only public internet addresses (checked at connection time), no redirects to other hosts, size / time / content-type
    limits, nothing on a page is ever run, no cookies or passwords, a daily visit limit, and a log of every visit. Values
    found on a site are only PROPOSALS that a person accepts; values outside the allowed range or that jump too far are
    quarantined; a changed security certificate or any security failure suspends the site automatically and tells the
    Head of Risk. Commercial sites (Bloomberg) are manual-only. A page that changes creates an action in the Daily Tracker.
    Official bodies mostly publish pages and PDFs, so a site is first linked in 'watch' mode (tells you when to update);
    you can add a text pattern later to propose the number itself.
  - Fix: the feed code now uses the same hardened connection; JSON/CSV feeds must declare their content type.

WHAT WAS NEW IN STEP 5  (Events & Fraud)
  - Weekly KPI (new module): your weekly KPI report as a live module. The starter set holds about 90 indicators with
    their history, taken from the July 2026 report: inflation, fuel and power, exchange rates and markets, money and
    credit, the payments sector, OTP-fraud and SIM-swap cases, transaction success rates against targets. Every value
    shows its as-of date, source and how it was captured (manual, import, feed, Sentinel); a value older than its
    reporting frequency is marked stale. Choose any as-of date (the default is the latest data). Commentary per group.
    Download Excel gives the report, the full history, the commentary and the sources.
    Updating: type a value, fill in the Excel template and import it (a checked preview comes first), approve a web feed
    (CSV or JSON) for an indicator, or let Sentinel calculate its own measures (risks assessed, outside appetite,
    overdue tasks, open incidents, net loss, KRIs in red). Feeds only reach hosts the administrator has approved, never
    follow redirects and never overwrite a value a person entered. Once a day after 06:00 Sentinel refreshes the feeds
    and its own measures; Refresh now does it on demand.
  - KRI Monitor: key risk indicators with amber and red thresholds, owner, linked risk, twelve-month red-amber-green
    strip and alerts. Amber tells the owner; red also tells the Head of Risk and opens an action in the Daily Tracker,
    which closes itself when the KRI is green again. Coverage shows which High and Significant risks have no KRI.
    Three starter KRIs come with the starter set; their thresholds are proposals for the owners to confirm.
  - Incidents & Losses: incidents, near misses and loss events linked to a risk and a control (or flagged), gross,
    recovered and net loss, loss by category and month, and the 24-hour personal-data-breach clock which stops when the
    regulator notification is recorded. A breach cannot be closed until the regulator is told; closing needs a root
    cause; closing an incident adds a re-assessment task for the linked risk. Serious incidents notify the Head of Risk.
  - Fix: the hourly Recycle Bin purge from Step 1 now saves its changes.

WHAT WAS NEW IN STEP 4
  - Daily Tracker: your Excel task tracker, brought in with all 65 tasks, statuses, owners, deadlines and the 11 e-mail
    links (Import Excel), in the same column order and with the same six dashboard tiles. Completion status and days
    remaining are calculated from your rule: Submitted or Completed = Completed; a revised date = Rescheduled; then
    Overdue, Due Soon (within 3 days) or On Track. Three flaws in the spreadsheet formula are fixed: On Hold and
    Cancelled tasks are no longer Overdue, a revised date that has itself passed shows Overdue, and there is a separate
    Due Today. Download Excel gives the tracker back in the original layout. Hybrid mode (recommended) also adds tasks
    automatically from risk action dates, assessment campaigns and Board decisions; Automatic and Manual are in the
    Automation tab. Events today and the end-of-day summary are included.
  - Risk Appetite (GRC Policy 2.4): target / appetite / tolerance thresholds taken from your risk assessment workbook
    (6 / 12 / 15 on the ranked matrix), the policy wording, appetite statements with limits and actual readings, the
    risks that are above appetite, and a version history. Changing a threshold needs a Board approval reference.
  - Assessment Studio: launch a campaign (for example the 33 imported risks), owners rate their risks (before and after
    controls, with evidence), and a different person reviews: approve (the register is updated) or challenge.
  - Board Hub: request a Board decision for a risk above appetite, record the decision with the minute and an expiry
    date (a different person records it), schedule meetings, and generate frozen, printable report packs (quarterly
    risk report for the Risk Committee, monthly report for the MD's meeting; GRC Policy 2.5).
  - Policy tolerance: the policy says a net score above 10 (old scale) is outside tolerable limits; the workbook sets
    tolerance at rank 15 on the ranked matrix. Sentinel follows the workbook and shows both; the Board should confirm.

WHAT WAS NEW IN STEP 3
  - Import your ISMS and BCMS risk assessment workbook: Risk Register > Import workbook. One safe step: it first
    checks the file and shows what will be imported (33 risks, 2,470 controls, $56.2M exposure) and any problems,
    and nothing is saved until you press Import. Running it twice is safe (risks already imported are skipped).
    Each sheet becomes a risk with its owner, root causes, implications, treatment, due date, linked controls
    (P2ST2 domain, owner, effectiveness ICE 2026), exposure EMV-i and action cost EMV-a.
  - Imported risks carry a placeholder 5 x 5 rating and are marked 'Needs assessment'. They are kept out of the
    heat map, Command Center ratings and snapshots until an owner enters a real rating (BRD decision D8).
  - Performance Analytics reproduces the Power BI pages from live data: Top 10, All risks and Balanced Scorecard,
    EMV (inherent, residual, action cost), Top 10 with P2ST2 effectiveness, Control Universe with a department
    slicer, and Departmental controls. Definitions: LoR = average ICE, LoA = 1 - LoR, EMV-r = EMV-i x LoR,
    RRR (transitional) = inherent likelihood x consequence x average ICE.
  - GRC Appendix I fields added to the register: subcategory and delegate. The CSV download now also carries the
    workbook reference, management system, strategic objective and EMV-a.
  - Safer shared browsers: if you sign in as another user in a second tab, the first tab now notices and reloads
    instead of showing the old user's screens. For testing several roles use a private window per user.
  - New users get a sensible default data scope from their role (oversight roles 'all', others 'own').
  - Database upgrades are automatic and keep all data (columns are added when Sentinel starts).

WHAT WAS NEW IN STEP 2
  - The auditor's ranked 5 x 5 matrix as a lookup table (Low 1-5, Medium 6-12, Significant 13-20, High 21-25).
  - Risk Register: add and edit risks with inherent, residual and target ratings; owner, root cause, treatment,
    dates; linked controls with effectiveness (ICE) giving level of assurance and EMV-r; suggested residual
    rating from control evidence; workflow Draft > Submitted > Reviewed > Approved > Closed with separation of
    duties; full history; delete to the Recycle Bin; download the register as CSV (opens in Excel).
  - Heat Map & Portfolio: inherent and residual maps with counts (click a cell), by category and status,
    quarter-end snapshots and movement.
  - Command Center: live KPIs, residual heat map, top five risks, categories, what needs attention, trend.
  - Data scope is enforced: 'own' sees own risks, 'function' the department's, 'all' everything.
  To explore quickly: as the administrator create a user with the role Head of Risk and data scope 'all',
  sign in as that user, open Command Center and press 'Load 14 sample risks' (they can be removed again).
  The administrator role deliberately cannot open risk data (separation of duties).

UPGRADING FROM STEP 1 OR 2 (your users and data are kept)
  1. Stop Sentinel (Ctrl+C in the black window).
  2. Run the new install_sentinel.py in the same folder as before (the folder that contains Sentinel).
     When it says a Sentinel folder exists, type y. Only program files are replaced; data is untouched.
  3. Start again with run.py.

What you had in Step 1: the secure sign-in, Access Management (users, roles, permissions, sign-in
policy), Administration (audit trail, Recycle Bin, outbox), My Profile and the application
shell with all 39 modules from the BRD. Modules other than the two above open a page that
describes what they will contain; they go live in the next steps.

You need: Windows 10 or 11 and Python 3.9 or newer (python.org). Nothing else to install.

START
  1. Double-click  run.bat   (or open a command window here and type:  py run.py).
  2. Your browser opens http://127.0.0.1:8000/login
  3. FIRST RUN ONLY: sign in as   admin   with the temporary password printed in the black
     window (also in data\FIRST_RUN_ADMIN.txt). Sentinel makes you choose your own password.
  4. Keep the black window open while you use Sentinel. Press Ctrl+C there to stop it.

FIRST THINGS TO DO (as admin)
  - Access Management > Users > "+ Add user": create the Head of Risk and a Risk Owner.
    The temporary password is shown once and is also in Administration > Outbox.
  - Sign in as that user in a private browser window to see the forced password change.
  - Access Management > Roles and permissions: see what each role may do.
  - Administration > Audit trail > "Verify chain": proves nothing was altered.

THE SIGN-IN RULES (from the BRD, section 5)
  - Username and password. Passwords change every 90 days (warning from 14 days before).
  - 3 wrong passwords in a row lock the account; the screen shows the attempts remaining.
  - Unlock: an administrator (Access Management), or "Forgot password?" on the sign-in page.
  - A user added by the administrator gets a temporary password (valid 48 hours) and must
    choose a new one at first sign-in. Admins can reset any password at any time.
  - Sessions end after 30 minutes idle; at most 2 sessions per user. Last 5 passwords cannot be reused.
  - Every value above can be changed in Access Management > Sign-in policy.

IF YOU ARE LOCKED OUT
  py manage.py reset-admin        gives admin a new temporary password (and unlocks it)
  py manage.py unlock USERNAME    unlocks any account
  py manage.py list-users         shows every user and status
  py manage.py verify-audit       checks the audit chain

YOUR DATA
  Everything is in the  data  folder (sentinel.db). To back up, stop Sentinel and copy that
  folder. (A Backup and Restore screen arrives in a later step.)

E-MAIL
  No mail server is connected yet. The messages Sentinel would send (invitations, reset
  links, lock alerts) appear in Administration > Outbox. Treat that page as confidential.

NETWORK USE
  Sentinel listens on this PC only (127.0.0.1). To let colleagues use it you must put it behind
  HTTPS first; do not simply open it to the network, because passwords would travel unencrypted.
  A later step adds the production setup. To change the port:  set SENTINEL_PORT=8001

CHECK THAT EVERYTHING WORKS
  py -m unittest discover -s tests -v      (277 automatic checks; takes about 155 seconds)

NOT YET BUILT (planned): Fraud Intelligence, Speak-Up Cases, Control Library & Testing, Actions & Issues, multi-factor sign-in, Backup/Restore and Export Centre screens, second-approver
permanent delete, Assessment Studio, Board Hub, Risk Appetite,
Daily Tracker and the other modules in the BRD.

TROUBLESHOOTING
  "py is not recognized": install Python from python.org and tick "Add python.exe to PATH".
  "Could not start the server ... port busy": another program uses port 8000; set SENTINEL_PORT=8001.


STEP 17 (version 0.16.0): clean-up and advanced stage
-----------------------------------------------------
* Build stages (P1 to P4) are gone from every user screen. Only the System Administrator sees them: Administration > Build and demo.
* Signing out is automatic: refreshing the page, pressing Back out of Sentinel, closing the tab or the browser ends the session on the server too.
  A new tab or a restored browser always asks you to sign in again.
* Charts: needle gauges (red, amber, green), radar, radial rings, lollipop, polar, treemap, waffle, bullet and sparklines replace repeated bars.
  The Performance Analytics pages (the Power BI replica) are unchanged on purpose.
* Profile pictures: My profile > Add photo (any picture is cropped square and shrunk in the browser). Shown in the top bar.
* Home shows an Enterprise risk pulse (gauges for appetite, assurance and high risks, plus risks by category) for people who may see the Command Center.
* Weekly KPI > Feeds and automation > Automatic research updates: every morning Sentinel opens each indicator's published source (the KPI_LINKS addresses) and, if needed,
  searches the web, reads the latest figure next to the indicator's words and records it with the page address and sentence. Mode: enter automatically, suggest only, or off.
  Readings found this way are marked "web". Sentinel only reads public pages; nothing is sent out.
* Demonstration data: Administration > Build and demo > Load / Remove, or from the console:  py manage.py demo-load   and   py manage.py demo-remove
  Everything is tagged "demo", and Remove takes out exactly that. py demo.py builds a separate demo folder that includes it.

STEP 18 (0.17.0)
- Weekly KPIs update themselves whenever the computer is online (commodities, exchange rates, stablecoins, World Bank). Check Weekly KPI > Feeds and automation; "Update now" shows what each service returned. Indicators with no public source (ZERA fuel, RBZ money supply, ZIMSTAT inflation, ZSE/VFEX) stay manual, import, or research suggestion (default: review).
- ZiG rate is a market rate (open.er-api), not the RBZ official rate.
- Imported KPI reports can be deleted (Weekly KPI > Enter): earlier values come back. The starter set can be removed too.
- Every page with demonstration data shows a "Remove it" bar.
- Control Library gauges fixed (chart bug). Login rules unchanged; the rules text is hidden.
- Financial year (1 March - end February) shows in the top bar and on Home. Now FY2027 Q3.
- Home redesigned with light background animation (pauses when hidden, off with reduced motion).

STEP 18 fix 1 (0.17.1)
- Fixed "database is locked" at sign-in and on every page when the laptop was online: the daily internet research held the database write lock while downloading pages. Internet work now runs with no lock held.

STEP 18 fix 2 (0.17.2)
- Background work can no longer make sign-in wait: a request that cannot get its turn within 25 seconds answers "busy" instead of hanging.
- Page-reading research is no longer automatic; it runs when a person presses Update now (Weekly KPI > Feeds and automation). Live prices stay automatic (light), starting 45 seconds after launch.
- http://127.0.0.1:8001/api/health shows the running version, process id and whether a task is holding things up. data\slow.log records any task that holds things up for more than 10 seconds.
- run.py now refuses to start a second copy on the same port and explains how to close the first. If sign-in is ever slow, check for an old window first: netstat -ano | findstr :8001

STEP 19 (0.18.0)
- Weekly KPI > Weekly report opens with a status card for today: live data, published statistics and EcoCash/Sentinel measures, each counted as up to date or waiting. "Bring report up to date" fetches every live figure at once and starts the report from that day.
- Deleted KPI imports, and the removed starter set, can be restored (Weekly KPI > Enter and import > What has been loaded).
- The Trends tab was removed (the report and charts already show history).
- Fixed "updated NaN h ago" on the live chip.
- Published statistics (ZIMSTAT, RBZ, ZERA, POTRAZ and so on) show the date they were really published; they update by import, research suggestion, or typing when the source releases them. EcoCash internal measures stay manual.

STEP 20 (0.19.0)
- New look: blue-globe background, glass infographic icon for every group and module, and a banner with the module's icon at the top of every page.
- Menu groups collapse and expand with the arrow at their right end; the group of the page you are on opens by itself, and Sentinel remembers your choices in this browser.
- "Smarter Risk. A Safer EcoCash." tile under the menu.
- Risk Register > Key: the full likelihood x consequence matrix (1-25), colour-coded by Sentinel's target, appetite and tolerance limits, with the auditor's ranked matrix beneath it.

STEP 20b (0.19.1)
- Backgrounds now match the EcoCash dashboard design: deep blue menu with the globe, red/blue swoosh and "Smarter Risk. A Safer EcoCash." at the bottom; world-map banner at the top of Home and every module; soft blue wave at the bottom of the page.
- Menu groups use bold full-colour icons; module icons are bright and clear. The green/teal tints on Home were replaced with blue.

Step 21 (version 0.20.0): weekly KPI report brought up to 17 November 2026
- sentinel/kpi_update_pack.json holds the figures read from the published sources (ZIMSTAT CPI to Oct 2026, RBZ rates of 12 Oct, ZERA fuel of 9 Oct).
  It loads once, as an import called "Update pack 17 Nov 2026", on "Bring report up to date" (or POST /api/kpi/pack/load). It can be deleted and restored like any import.
- Live now: RBZ daily rate sheet (USD, EUR, GBP, BWP, ZAR), ZERA pump prices, stablecoins from Yahoo Finance (CoinGecko as back-up), plus the earlier commodities and World Bank.
  The "How" column shows Live (green) when the latest figure came from a feed, and "Live feed" before the first fetch.
- Bloomberg has no public feed: stablecoins use Yahoo Finance, the nearest free equivalent.
- Not live (the sites forbid or hide their data): ZESA generation, ZSE and VFEX market capitalisation. Enter them by hand, by file, or from the research suggestions.
- The RBZ and ZERA readers could not be tried against the real sites from the build machine. On the laptop press Update now (Weekly KPI, Feeds and automation); any problem is listed by name.

Step 21 fix (version 0.20.1)
- Risk Register: "Import the assessment workbook" and "Saved workbooks" (download, delete, restore from the Recycle Bin) are now on every tab, including All risks.
- Key tab: the workbook's likelihood x consequence matrix and the external auditor's ranked matrix now sit side by side.
- Weekly KPI: a "Workbooks: delete / restore" button at the top of the report goes to the import list with Delete and Restore.
- All 99 catalogue KPIs are created automatically if any is missing (definitions only, no demonstration figures), so gold, platinum, EUR, stablecoins and the rest always appear.

Step 22 (version 0.21.0)
- KRI Monitor now has four tabs: Monitor, Dashboard, Report, Enter and import.
- Quarterly KRI dashboards from Q4 FY26 to date (17 risks, 76 KRIs from the BoT and RISCO decks). Charts: status trend, scorecard, heat grid, KRI trends.
- Enter and import: import a quarterly Excel or PowerPoint (Check first, then Import) or type figures by hand. The dashboards and report update at once. Imports can be deleted and restored.
- Interpreted KRI report (what improved, worsened, persistent breaches, figures that differ between report versions).
- Downloads: PowerPoint with native charts, and a Power BI data pack (Excel star schema: Fact_KRI, Dim_KRI, Dim_Risk, Dim_Quarter, Fact_Residual). A .pbix/.pbip report itself is not generated.
- Copilot: live price answers (gold, platinum, fuel, rates) when online; web results are filtered for relevance; Claude mode (AI Governance) gives claude.ai-style answers to any question.

Step 23 (version 0.22.0)
- KRI Monitor > Power BI pages: 15 pages drawn from the stored KRI figures, in the style of the EcoCash Power BI report. Executive Overview, Residual Risk Rating Movement, Indicator Universe, Monetary Exposure, and the risk pages (Business Performance, Operating Expenses & Economic, Strategic, Compliance & Regulatory, Cyber Security & Fraud, BCM & Technology, People & Customer, Credit & Third-Party, Board Trust Risks, two Additional KRI pages). Page tabs run along the bottom.
- Traffic lights: every KRI row, chart, scorecard row and indicator carries a lamp. Red (pulsing) = off target, amber = near target (within 10%), green = on target, all dark = no target.
- Edit figures: every risk section and every Power BI page has an Edit figures button: correct any quarter, add the next quarter, empty a box to remove a figure, add a KRI, remove a KRI. Every save is a batch that can be deleted and restored. Removed KRIs are listed under Enter and import with Restore.
- Power BI residual ratings (whole numbers, GRC scale: inherent 25, appetite 10) and the KRIs that appear only in the Power BI report are loaded as one batch "Power BI report: residual ratings and extra KRIs" (read from the screenshots; check against the report). Delete that batch to go back to the committee decks' own ratings.
- Downloads: the PowerPoint now has the executive pages and one slide of up to six native charts per risk page; the Power BI data pack gains Risk_Movement and Indicator_Universe sheets.
- Not yet built (they are fed by tables outside the KRI figures): Macro-Economic Environment, Payments Landscape, National Payment System, Contact Centre, Regulatory and Emerging Drivers, Trust Account Bank Exposure.
