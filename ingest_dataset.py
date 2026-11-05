"""Bulk-ingest every PDF in ./papers into Neo4j"""
import glob, os, core
core.setup()
for p in sorted(glob.glob("papers/*.pdf")):
    print(core.ingest(p, os.path.basename(p)))
