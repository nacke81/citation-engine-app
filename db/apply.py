"""Apply db/schema.sql to the hosted project via the Supabase Management API (idempotent).
Usage: python db/apply.py <project_ref>   (SUPABASE_ACCESS_TOKEN from the environment; never printed)"""
import json, os, sys, urllib.request

ref = sys.argv[1]
sql = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql"), encoding="utf-8").read()
req = urllib.request.Request(f"https://api.supabase.com/v1/projects/{ref}/database/query", method="POST",
                             data=json.dumps({"query": sql}).encode(),
                             headers={"Authorization": "Bearer " + os.environ["SUPABASE_ACCESS_TOKEN"],
                                      "Content-Type": "application/json", "User-Agent": "citation-engine"})
with urllib.request.urlopen(req, timeout=60) as r:
    print("applied:", r.status)
check = ("select c.relname, c.relrowsecurity, c.relforcerowsecurity, "
         "(select count(*) from pg_policies p where p.tablename = c.relname) as policies "
         "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
         "where n.nspname = 'public' and c.relname like 'ce\\_%' and c.relkind = 'r' order by 1")
req = urllib.request.Request(f"https://api.supabase.com/v1/projects/{ref}/database/query", method="POST",
                             data=json.dumps({"query": check}).encode(),
                             headers={"Authorization": "Bearer " + os.environ["SUPABASE_ACCESS_TOKEN"],
                                      "Content-Type": "application/json", "User-Agent": "citation-engine"})
for row in json.load(urllib.request.urlopen(req, timeout=60)):
    print(row)
