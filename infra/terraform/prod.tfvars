project_id = "ai-holding-prod-bc"
region     = "southamerica-east1"

# PAPER/SHADOW stays disabled until an immutable image digest exists and the
# authorized market-data secret has a version. LIVE is not part of this stack.
deploy_paper_shadow = false
runtime_image_ref   = ""
