#!/bin/bash
# Re-scrape on the fixed adapters, then two independent 30/20 batches.
# Kept separate so they can be reviewed one at a time.
set -e
cd "$(dirname "$0")"
echo "=== 1/3  re-scrape (adapters v3: no mailing addresses, full location lists) ==="
python3 -u pool.py --skip designjobsworld
echo
echo "=== 2/3  batch A ==="
python3 -u batch.py
python3 - <<'PY'
import json, shutil
import pool as P
d=json.load(open('data/review.json'))
json.dump({"name":"batchA","criteria":d['note'],"roles":d['roles']},
          open('data/fixtures/batchA.json','w'),indent=1,ensure_ascii=False)
shutil.copy('data/review.json','data/review_batchA.json')
seen=set(json.load(open('data/reviewed.json')))
for r in d['roles']: seen.add(P.identity(r['company'],r['title']))
json.dump(sorted(seen),open('data/reviewed.json','w'),indent=1)
print('batch A saved; reviewed identities now %d'%len(seen))
PY
echo
echo "=== 3/3  batch B ==="
python3 -u batch.py
python3 - <<'PY'
import json, shutil
import pool as P
d=json.load(open('data/review.json'))
json.dump({"name":"batchB","criteria":d['note'],"roles":d['roles']},
          open('data/fixtures/batchB.json','w'),indent=1,ensure_ascii=False)
shutil.copy('data/review.json','data/review_batchB.json')
seen=set(json.load(open('data/reviewed.json')))
for r in d['roles']: seen.add(P.identity(r['company'],r['title']))
json.dump(sorted(seen),open('data/reviewed.json','w'),indent=1)
print('batch B saved; reviewed identities now %d'%len(seen))
PY
# leave A loaded, since that is the one he asked for first
cp data/review_batchA.json data/review.json
echo
echo "=== DONE — batch A is loaded at http://localhost:8123/review.html ==="
