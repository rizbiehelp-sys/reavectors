# reavectors helper scripts
#
# These read secrets from the repo-root `.env` (git-ignored). Nothing here
# contains a secret, so it is safe to keep in the public repo.
#
#   . ..\scripts\load-env.ps1         # load .env into the current shell
#   .\scripts\render-set-env.ps1      # push runtime env vars to Render
#   .\scripts\render-deploy.ps1       # trigger a Render deploy
#   .\scripts\supabase-sql.ps1 "select 1"   # run SQL on your Supabase project
#
# Requires: RENDER_API_KEY (+ RENDER_SERVICE_ID) and/or SUPABASE_ACCESS_TOKEN in .env
