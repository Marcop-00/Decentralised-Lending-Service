REMEDIATION STEPS - Sensitive keys found in repository

Summary
-------
This repository contained an Ethereum keystore file and a password file committed into source control. These are sensitive secrets and must be treated as compromised.

Actions taken (current branch only)
----------------------------------
- Removed the keystore and password files from the current working tree and staged the removal.
- Added ignore rules to .gitignore to prevent re-adding similar files.
- Created this REMEDIATION.md with guidance on next steps.

Immediate next steps (recommended)
---------------------------------
1. Rotate any accounts whose keys were present in the repository immediately. Assume they are compromised.
2. If those accounts were used on any network, move funds to newly generated accounts as soon as possible.
3. If the keys must be removed from the git history entirely, use a history-rewriting tool such as `git filter-repo` or the BFG Repo-Cleaner. This is a destructive operation — coordinate with teammates and force-push to the repo after taking backups.
4. After rewriting history, revoke any credentials or secrets that relied on the removed keys and update deployment pipelines to use secrets management.
5. Add encrypted secrets or environment variables to CI and local .env files (never commit plaintext secrets).

How to purge secrets from history (brief)
----------------------------------------
# Example using git filter-repo (install separately):
# git clone --mirror <repo-url>
# cd repo.git
# git filter-repo --path "data/keystore/UTC--2026-05-05T14-09-10.723312492Z--d278d247a52c550508ea2b2c9321d816238fb523" --invert-paths
# git filter-repo --path "0xd278d247A52C550508ea2b2C9321d816238fb523psw.txt" --invert-paths
# git push --force --all

Notes
-----
- The files were removed from the current branch working tree and a commit was created. However, they may still exist in previous commits accessible in the repo history until the repository history is cleaned.
- Do NOT share the original files or their contents with third parties.

