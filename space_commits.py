import subprocess
from datetime import datetime, timedelta

# Get all commits in chronological order
result = subprocess.run(["git", "log", "--reverse", "--format=%H"], capture_output=True, text=True)
commits = [c for c in result.stdout.strip().split('\n') if c]

if not commits:
    print("No commits found.")
    exit()

# Define the timeframe (April 1, 2026 to now)
start_date = datetime(2026, 4, 1, 10, 0, 0)
end_date = datetime.now()
total_seconds = (end_date - start_date).total_seconds()

# Calculate the interval between each commit
interval = total_seconds / max(1, len(commits) - 1)

# Generate the case statements mapping each hash to its new date
case_statements = ""
for i, commit in enumerate(commits):
    commit_date = start_date + timedelta(seconds=i * interval)
    date_str = commit_date.strftime('%Y-%m-%dT%H:%M:%S')
    case_statements += f'''
    {commit})
        export GIT_AUTHOR_DATE="{date_str}"
        export GIT_COMMITTER_DATE="{date_str}"
        ;;'''

# Construct the final filter-branch script
bash_script = f'''#!/bin/bash
export FILTER_BRANCH_SQUELCH_WARNING=1
git filter-branch -f --env-filter '
case $GIT_COMMIT in {case_statements}
esac
' -- --all
'''

with open("rewrite_dates.sh", "w") as f:
    f.write(bash_script)

print("Generated rewrite_dates.sh successfully.")