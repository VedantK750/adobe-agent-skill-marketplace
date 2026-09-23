# Round 4 recording cheat sheet - PowerShell
# TransformerBusters
#
# Every command below has been run and verified on this machine.
# Paste them one at a time. Do NOT run this file as a script.
#
# NOTE ON PYTHON: this machine has `py -3`, not `python3`. The manifest
# documents both. Keep using `py -3` on camera.

# ---------------------------------------------------------------------------
# 0. BEFORE YOU HIT RECORD
# ---------------------------------------------------------------------------
# - Increase terminal font (Ctrl + Shift + +) so text is readable in video.
# - Maximise the window; close other tabs/panes.
# - Have https://razorpay.com/robots.txt open in a browser tab, ready to show.
# - Confirm you are in the repo root:

cd C:\Users\saart\adobe-agent-skill-marketplace
Get-Location

# - Clear any previous run so the audit happens live on camera:
Remove-Item -Recurse -Force .\audit-run -ErrorAction SilentlyContinue

# - Clear the screen right before the take:
Clear-Host


# ---------------------------------------------------------------------------
# 1. WIRING - prove it is the Round 3 marketplace, not a hardcoded demo  (~15s)
# ---------------------------------------------------------------------------
# Say: "Eight skills, exactly one entrypoint, declared in the manifest."

py -3 -c "import json;m=json.load(open('marketplace.json'));print('marketplace:',m['name'],m['version']);[print(('  ENTRYPOINT ' if s.get('entrypoint') else '             ')+s['id']) for s in m['skills']]"


# ---------------------------------------------------------------------------
# 2. THE LIVE RUN  (~19 seconds - do not trim the start)
# ---------------------------------------------------------------------------
# Say the harness + model out loud here. It is a scored line:
#   "Claude Code v2.1.280 driving Claude Opus 5, invoking the Round 3
#    entrypoint skill. The agent reads marketplace.json, finds the entrypoint,
#    and runs what its SKILL.md documents."
#
# Type the URL on camera. This is the continuity the integrity gate cares
# about - from here to the findings there must be no cut except idle waiting.

py -3 skills/audit-orchestrator/scripts/run_audit.py --url https://razorpay.com/ --workdir ./audit-run --max-pages 10 --no-render --markdown


# ---------------------------------------------------------------------------
# 3. SUMMARY  (~10s)
# ---------------------------------------------------------------------------

py -3 -c "import json;r=json.load(open('audit-run/audit-report.json',encoding='utf-8'));s=r['summary'];m=r['audit_meta'];print('%s | %s | %d pages | %d findings: %d critical, %d high, %d medium, %d low'%(r['site'],m['site_type'],m['pages_crawled'],s['total_findings'],s['critical'],s['high'],s['medium'],s['low']))"


# ---------------------------------------------------------------------------
# 4. PRIORITISATION  (~15s)
# ---------------------------------------------------------------------------
# Say: "Sorted by severity, then by ascending effort - so among equally severe
#       findings the cheapest fix comes first."

py -3 -c "import json;r=json.load(open('audit-run/audit-report.json',encoding='utf-8'));[print('%-6s %-9s %-26s %s'%(f['id'],f['severity'],f['check_id'],f['suggested_action'].get('effort','')+' effort')) for f in r['findings'][:8]]"


# ---------------------------------------------------------------------------
# 5. DRILL INTO THE CRITICAL FINDING  (~35s) - the most important shot
# ---------------------------------------------------------------------------

py -3 -c "import json,textwrap;r=json.load(open('audit-run/audit-report.json',encoding='utf-8'));f=r['findings'][0];a=f['suggested_action'];w=lambda t,i='  ':print(textwrap.fill(t,96,initial_indent=i,subsequent_indent=i));print('%s  %s  %s'%(f['id'],f['severity'].upper(),f['title']));print();print('WHY IT MATTERS');w(f['mechanism']);print();print('EVIDENCE');w(f['evidence']);print();print('FIX (%s priority, %s effort)'%(a['priority'],a['effort']));w(a['summary']);[w('- '+s) for s in a['steps'][:3]];print();print('VERIFY');w(a['verification'])"

# NOW SWITCH TO THE BROWSER TAB: https://razorpay.com/robots.txt
# Point at the two lines:   User-agent: Bytespider
#                           Disallow: /
# Say: "That is the finding, corroborated against the live site."
# This is the strongest ten seconds in the video - do not rush it.


# ---------------------------------------------------------------------------
# 6. CLOSE ON REPRODUCIBILITY  (~15s)
# ---------------------------------------------------------------------------
# Say: "Same command is step 2 of REPLAY_TransformerBusters.txt. Analysis is a
#       pure function of the crawl snapshot, so a judge re-running this gets
#       the same substance."

Get-ChildItem .\audit-run -Name


# ---------------------------------------------------------------------------
# OPTIONAL - second site, only if Part 2 is comfortably under 2:00
# ---------------------------------------------------------------------------
# postman.com serves ~101 KB of HTML that yields ONE word of readable text.
# "A human sees a full page; a machine that does not run JavaScript sees
#  nothing." Also critical, different mechanism.

# py -3 skills/audit-orchestrator/scripts/run_audit.py --url https://www.postman.com/ --workdir ./audit-run-postman --max-pages 10 --no-render --markdown


# ---------------------------------------------------------------------------
# AFTER RECORDING - clean up the working dirs (they are gitignored anyway)
# ---------------------------------------------------------------------------
# Remove-Item -Recurse -Force .\audit-run, .\audit-run-postman -ErrorAction SilentlyContinue
