rsync -avzhe ssh --delete \
    --exclude '.DS_Store' \
    --exclude '.git' \
    --exclude '.gitignore' \
    --exclude '_deploy.sh' \
    --exclude '*.conf' \
    --exclude '*.pyc' \
    --exclude '*.log' \
    --exclude 'logs' \
    --exclude 'README_VMWARE.md' \
    ../migrate2cs/ <user>@<server_ip>:/path/to/migrate2cs