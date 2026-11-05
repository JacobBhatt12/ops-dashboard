"""Agency Finder: web design and SEO agencies, found on Google Maps.

  scrape.py    run the gosom/google-maps-scraper Docker image, qualify results
  cities.py    the cities each state is searched in
  store.py     SQLite agency database (data/agencies.db)
  template.py  the lead-gen pitch email sent to agencies
  bridge.py    hands approved agencies to the outreach bot
  settings.py  dashboard-editable settings (data/agencyfinder.json)
  run.py       CLI: scrape / nightly / status / preview
  api.py       dashboard endpoints for the Agencies tab
"""
