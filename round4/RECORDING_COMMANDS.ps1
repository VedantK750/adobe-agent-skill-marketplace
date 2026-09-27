# Round 4 recording reference - TransformerBusters
#
# =========================================================================
#  PART 2 IS AN AGENT SESSION, NOT THESE COMMANDS.
#
#  The brief: "A CLI-based session in which an AI agent runs your
#  marketplace and reports its findings is exactly what we want to see.
#  The interface is the agent interaction itself."
#
#  So the demo is: open Claude Code in this repo, paste ONE prompt, and let
#  it work. See "PRIMARY" below.
#
#  The PowerShell commands further down are the FALLBACK path only - the
#  same one documented in REPLAY_TransformerBusters.txt for judges who do
#  not have Claude Code. If you record with those, you must say on camera
#  that you are running the entrypoint directly, because claiming "Claude
#  Code is driving this" while running raw python is a video/manifest
#  mismatch and an automatic integrity failure.
# =========================================================================


# -------------------------------------------------------------------------
# PRIMARY - what to record
# -------------------------------------------------------------------------
# 1. Open Claude Code in C:\Users\saart\adobe-agent-skill-marketplace
# 2. Say on camera: "Claude Code v2.1.283 running Claude Opus 5."
# 3. Type this prompt (the URL goes in on camera):
#
#    Read marketplace.json, then follow skills/audit-orchestrator/SKILL.md
#    (the entrypoint skill) to audit https://razorpay.com/ with
#    --max-pages 10 --no-render. Report the findings by severity with the
#    evidence for each, and name the top three fixes in priority order.
#
# 4. Let it run (~20s of audit). You will see it read marketplace.json,
#    open the entrypoint SKILL.md, and invoke run_audit.py - that is the
#    "one line on wiring" requirement satisfied on screen.
#
# 5. If its summary is thin on any single finding, ask in the same session:
#
#    Show me the full evidence, mechanism, fix steps and verification for
#    the critical finding.
#
# 6. Switch to the browser: https://razorpay.com/robots.txt
#    Point at:  User-agent: Bytespider
#               Disallow: /
#    Say: "That is the finding, corroborated against the live site."
#
# 7. Close: "Same run is step 2 of REPLAY_TransformerBusters.txt, and the
#    analysis is a pure function of the crawl snapshot."


# -------------------------------------------------------------------------
# BEFORE YOU RECORD (either path)
# -------------------------------------------------------------------------
cd C:\Users\saart\adobe-agent-skill-marketplace
Remove-Item -Recurse -Force .\audit-run, .\audit-run-postman -ErrorAction SilentlyContinue
Clear-Host
# Bump the terminal font: Ctrl + Shift + +
# Open https://razorpay.com/robots.txt in a browser tab, ready to switch to.


# =========================================================================
# FALLBACK ONLY - if Claude Code misbehaves mid-recording.
# If you use these, say "running the entrypoint directly - this is the
# fallback path documented in the manifest."
# =========================================================================

# Wiring: eight skills, exactly one entrypoint
py -3 -c "import json;m=json.load(open('marketplace.json'));print('marketplace:',m['name'],m['version']);[print(('  ENTRYPOINT ' if s.get('entrypoint') else '             ')+s['id']) for s in m['skills']]"

# The audit (~19s)
py -3 skills/audit-orchestrator/scripts/run_audit.py --url https://razorpay.com/ --workdir ./audit-run --max-pages 10 --no-render --markdown

# Summary
py -3 -c "import json;r=json.load(open('audit-run/audit-report.json',encoding='utf-8'));s=r['summary'];m=r['audit_meta'];print('%s | %s | %d pages | %d findings: %d critical, %d high, %d medium, %d low'%(r['site'],m['site_type'],m['pages_crawled'],s['total_findings'],s['critical'],s['high'],s['medium'],s['low']))"

# Prioritised list - severity, then ascending effort
py -3 -c "import json;r=json.load(open('audit-run/audit-report.json',encoding='utf-8'));[print('%-6s %-9s %-26s %s'%(f['id'],f['severity'],f['check_id'],f['suggested_action'].get('effort','')+' effort')) for f in r['findings'][:8]]"

# Drill into the critical finding
py -3 -c "import json,textwrap;r=json.load(open('audit-run/audit-report.json',encoding='utf-8'));f=r['findings'][0];a=f['suggested_action'];w=lambda t,i='  ':print(textwrap.fill(t,96,initial_indent=i,subsequent_indent=i));print('%s  %s  %s'%(f['id'],f['severity'].upper(),f['title']));print();print('WHY IT MATTERS');w(f['mechanism']);print();print('EVIDENCE');w(f['evidence']);print();print('FIX (%s priority, %s effort)'%(a['priority'],a['effort']));w(a['summary']);[w('- '+s) for s in a['steps'][:3]];print();print('VERIFY');w(a['verification'])"

# Outputs
Get-ChildItem .\audit-run -Name
