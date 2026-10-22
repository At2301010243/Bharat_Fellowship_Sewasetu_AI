# Running Sewa Setu in a GitHub Codespace

This guide explains how to start the Sewa Setu project in a Codespace, open it
in a browser, and stop or remove the Docker resources when finished. Stopping
the services is important because running containers consume Codespace compute
hours. Docker volumes and images consume storage even after containers stop.

## 1. Open the project in a Codespace

1. Open the repository on GitHub.
2. Select **Code** > **Codespaces** > **Create codespace on main** (or on the
   branch you want to use).
3. Wait for the VS Code web editor to finish loading.
4. Open the integrated terminal with **Terminal** > **New Terminal**.
5. Confirm that the terminal is at the repository root:

   ```bash
   pwd
   ls
   ```

   The root should contain `docker-compose.yml`, `app/`, and `smsgw/`.

## 2. Start the Docker project

Run this from the repository root:

```bash
docker compose up --build -d
```

What this starts:

- `app`: the Flask/Gunicorn Sewa Setu website
- `db`: PostgreSQL database
- `smsgw`: simulated SMS gateway
- `scheduler`: the deemed-approval background scheduler

The first run may take several minutes because Docker downloads the PostgreSQL
image and builds the application images. The database is initialized from
`app/schema.sql` and `seed/seed.sql`.

To check that all services are running:

```bash
docker compose ps
```

Each service should show a status such as `Up`. The website is published from
the Codespace on port `8000`.

## 3. Open and use the website

### Option A: Open the forwarded port in VS Code

1. Open the **Ports** panel in VS Code.
2. Find port `8000`.
3. Click the globe/open-browser icon, or right-click the port and select
   **Open in Browser**.

### Option B: Open it from the terminal

Visit:

```text
http://localhost:8000
```

If the browser rewrites the address to `127.0.0.1`, that is normal for a
forwarded Codespace port.

Useful pages:

- Main portal: `http://localhost:8000/`
- Application status: `http://localhost:8000/status`
- Departmental login: `http://localhost:8000/admin`
- Simulated SMS gateway: `http://localhost:8000/__gateway/`

The default development admin username is `admin`. Set a different password
before starting the project if needed:

```bash
ADMIN_PASSWORD='choose-a-development-password' docker compose up --build -d
```

Do not use the default password for a public deployment.

## 4. View logs and troubleshoot

View recent logs for all services:

```bash
docker compose logs --tail=100
```

Follow the website logs:

```bash
docker compose logs -f app
```

Press `Ctrl+C` to stop following logs. This does not stop the containers.

Check the website directly from the terminal:

```bash
curl -I http://localhost:8000/
```

A working service returns `HTTP/1.1 200 OK`.

## 5. Stop the project when temporarily finished

To stop the containers but keep the database and uploaded files:

```bash
docker compose stop
```

This is the safest choice if you plan to continue working later. Restart the
same containers with:

```bash
docker compose start
```

Stopping the containers prevents them from using runtime compute, but their
Docker images and volumes still use Codespace disk storage.

## 6. Remove the project containers when finished

To stop and remove the project containers and network, while preserving the
named volumes:

```bash
docker compose down
```

Run this when you are done for the day and want to clean up the running Docker
resources. To start again later, use:

```bash
docker compose up --build -d
```

## 7. Delete the project data and Docker storage

**Warning:** The following command permanently deletes this project's
PostgreSQL database, uploaded files, and application logs stored in Docker
volumes. Use it only when you no longer need the local Codespace data:

```bash
docker compose down -v
```

The `-v` option removes the volumes declared by this project:

- `pgdata`
- `uploads`
- `applogs`

The next `docker compose up --build -d` will create a fresh database and load
the seed data again.

To see Docker disk usage before cleaning:

```bash
docker system df
```

If you have confirmed that unused Docker images, stopped containers, networks,
and volumes from other projects can be removed too, use the narrower cleanup
commands below:

```bash
docker container prune
docker image prune
docker network prune
docker volume prune
```

Each command asks for confirmation. These commands can affect other projects
in the same Codespace, so do not run them if you need those resources.

## 8. Stop or delete the Codespace itself

Docker cleanup and Codespace cleanup are separate:

- **Stop the Codespace**: pauses the machine and prevents ongoing compute
  usage. The Codespace and its files remain available.
- **Delete the Codespace**: permanently removes the Codespace machine and its
  files. Do this only after pushing or downloading any work you need.

From GitHub:

1. Open your GitHub profile menu.
2. Select **Codespaces**.
3. Find the Codespace for this repository.
4. Use the `...` menu.
5. Select **Stop codespace** when you will return later.
6. Select **Delete** when you are finished permanently.

Before deleting, a complete cleanup sequence is:

```bash
docker compose down -v
git status
git push
```

Only run `git push` if you want to preserve your committed or staged project
work on GitHub. Untracked files and uncommitted changes should be committed or
downloaded first if they must be kept.

## Quick cleanup checklist

Use this checklist at the end of a session:

```bash
# Keep project data for later
docker compose stop

# Or remove containers and the project network
docker compose down

# Or remove containers plus this project's database/uploads/logs
docker compose down -v
```

Then stop the Codespace from GitHub if you will not use it again today. Delete
the Codespace only when you are certain that all required work has been pushed
or backed up.
