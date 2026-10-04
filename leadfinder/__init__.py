"""Lead Finder: free nationwide small-business lead sourcing for TheraWeb.

  overture.py  pull small businesses from the open Overture Maps dataset
  crawler.py   visit each business website, find a published email, note issues
  store.py     SQLite lead database (data/leads.db)
  template.py  the business outreach email
  settings.py  dashboard-editable settings (data/leadfinder.json)
  run.py       CLI: import / crawl / status
"""
