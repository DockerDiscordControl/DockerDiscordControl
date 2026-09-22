# GitHub Actions Workflows

## 🐳 Docker publishing: one build, four names

`docker-publish.yml` builds **one** image from `./Dockerfile` for `linux/amd64` and
`linux/arm64` and pushes it under all four Docker Hub names:

| Docker Hub name | Note |
|-----------------|------|
| `dockerdiscordcontrol/dockerdiscordcontrol` | Main name, used by the Unraid template |
| `dockerdiscordcontrol/dockerdiscordcontrol-linux` | Same image |
| `dockerdiscordcontrol/dockerdiscordcontrol-mac` | Same image |
| `dockerdiscordcontrol/dockerdiscordcontrol-windows` | Same image |

Until v2.4.1 the three platform names were published from three copied repositories
(DockerDiscordControl-Linux, -Mac, -Windows), each with its own build. The copies had
drifted and the four `latest` tags carried four different digests. Those repositories
are archived after the first release that fills all four names from here.

The old platform-only tags (`:mac`, `:apple-silicon`, `:linux`, `:windows` and similar)
are no longer written since v2.4.

### `docker-publish.yml`
- **Triggers:** push to `main`, tags `v*`, pull requests to `main` (build only, no push), manual dispatch
- **Gate:** the `test` job runs every group in `tests/GROUPS.txt`; `build_and_push` needs it (SPEC.md Z10)
- **Tags:** `latest` and `unraid` on the default branch, semantic versions, `sha`
- **Pushes:** all four names above, from one `docker/metadata-action` list

### `dockerhub-readme-sync.yml`
- **Triggers:** push to `main` that changes `README.md` or this workflow, manual dispatch
- Writes the Docker Hub overview of all four names from the one `README.md`, each with
  its own short description (Docker Hub keeps at most 100 characters of it)

Both rules - exactly these four names, and no other workflow pushes an image or writes a
Hub description - are pinned by `tests/spec/test_one_build_feeds_all_four_image_names.py`.

## ⚡ Pull

```bash
docker pull dockerdiscordcontrol/dockerdiscordcontrol:latest
```
