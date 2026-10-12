from pathlib import Path
source=Path('C:/Users/lucys/Documents/Codex/2026-08-25/yo/work/commons-spark-link/integrations/shared_equipment/native_codex_mcp_custody.mjs').read_text()
# Actual current age header factor19 requires512MiB. Preserve original current
# available-commit reservation and every authentication/decryption check.
source=source.replace('if(work>18||work<1)','if(work>19||work<1)')
source=source.replace("path.join(here,'native_codex_mcp_passphrase.py')","'C:/Users/lucys/Documents/Codex/2026-08-25/yo/work/commons-spark-link/integrations/shared_equipment/native_codex_mcp_passphrase.py'")
Path('reviewed_native_custody.mjs').write_text(source)
