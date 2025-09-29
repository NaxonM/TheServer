# File Proxy System

This repository contains a simple, self-hosted file proxy system designed for easy, single-command deployment. It uses Docker and Traefik to provide a secure, SSL-enabled service for proxying and storing remote files.

## Core Features

-   **Web Dashboard**: Manage proxied files, view system stats, and monitor active downloads.
-   **Secure File Proxying**: Download files from remote URLs and serve them from your own domain.
-   **Automatic SSL**: Traefik integration with Let's Encrypt provides automatic SSL certificate generation and renewal.
-   **Automated Cleanup**: A cron job periodically cleans up old files to save disk space.
-   **Containerized**: All components are containerized for portability and isolation.

## Deployment

To deploy the system, you need a server with `Docker` and `git` installed. The installation process is fully interactive and will guide you through the setup.

To install from the `main` branch (default):
```bash
bash <(curl -sSL https://raw.githubusercontent.com/NaxonM/TheServer/main/install.sh)
```

To install from a specific branch (e.g., `dev`):
```bash
bash <(curl -sSL https://raw.githubusercontent.com/NaxonM/TheServer/main/install.sh) dev
```

## Updating the System

The installation script is idempotent. To update your application to the latest version, simply run the original installation command again. The script will automatically detect the existing installation, pull the latest code, and redeploy the containers without deleting any of your data.

## Uninstallation

To completely remove the File Proxy System and all its associated data (containers, volumes, and configuration files), run the installer with the `uninstall` argument:

```bash
curl -sSL https://raw.githubusercontent.com/NaxonM/TheServer/main/install.sh | bash -s uninstall
```

You will be asked for confirmation before any data is deleted.