# -*- coding: utf-8 -*-
"""The image-update check compares the image the container RUNS, not what its tag points to.

THE FINDING (audit 2026-09-26, F12). The check read Config.Image - the tag,
"nginx:latest" - and asked Docker for THAT image's digests. After a
`docker pull` without recreating the container, the tag already points at the
new image while the container still runs the old one: local and remote
digests matched, and the check said "no update" for a container that was in
fact out of date - until it was recreated, which is exactly the step the
notice exists to prompt.

THE CONTRACT: the local digests are those of the image id in the container's
own "Image" field; the tag only names the repository to ask the registry
about.

COUNTER-CHECK (2026-09-26): red before the fix - read_running_image did not
exist; the loop read client.images.get(<tag>), which returns the new digest.
"""

from types import SimpleNamespace

from services.automation.image_updates import read_running_image, update_available

OLD = "sha256:" + "a" * 64
NEW = "sha256:" + "b" * 64


class _Client:
    def __init__(self):
        container = SimpleNamespace(attrs={"Config": {"Image": "nginx:latest"}, "Image": "sha256:" + "1" * 64})
        images = {
            # the image the container runs - pulled long ago
            "sha256:" + "1" * 64: SimpleNamespace(attrs={"RepoDigests": [f"nginx@{OLD}"]}),
            # what the tag points to after `docker pull nginx:latest`
            "nginx:latest": SimpleNamespace(attrs={"RepoDigests": [f"nginx@{NEW}"]}),
        }
        self.containers = SimpleNamespace(get=lambda name: container)
        self.images = SimpleNamespace(get=lambda name: images[name])


def test_the_running_image_is_compared():
    image_name, ref, local = read_running_image(_Client(), "web")

    assert image_name == "nginx:latest"
    assert local == {OLD}
    assert update_available(NEW, local) is True


def test_a_container_on_the_newest_image_has_no_update():
    """Counter-case."""
    _name, _ref, local = read_running_image(_Client(), "web")

    assert update_available(OLD, local) is False
