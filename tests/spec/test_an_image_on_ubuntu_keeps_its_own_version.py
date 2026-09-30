# -*- coding: utf-8 -*-
"""An image built on ubuntu that labels its own version shows that version.

THE FINDING (stage 4 review before v3.1.0, section 19b pass 4 F6):
version_of skipped org.opencontainers.image.version whenever
org.opencontainers.image.ref.name named a base system. ubuntu 22.04+ sets
both, so a child image inherits them - but docker/metadata-action, the
usual way to label an image in CI, overwrites the version and leaves
ref.name alone. Such an image's own version was thrown away as "inherited",
and without a numeric tag the info display showed the image date.

THE CONTRACT: the version counts as inherited only while the image does not
name itself (no org.opencontainers.image.title or .source; ubuntu sets
neither, metadata-action sets both). The pure inheritance case (carmeet-api,
measured 2026-09-28) stays hidden.

NOT CHECKED: a child that sets a title or source but no version of its own
would now show the base system's "22.04". No such image was measured; the
labels alone cannot tell it apart from the case above.

HOW THIS TEST CAN FAIL: the own version is skipped again, or the inherited
one comes back.

COUNTER-CHECK (2026-09-30): red before the change (None for the labelled image).
"""

from services.infrastructure.container_facts_service import facts_from_attrs, version_of

UBUNTU = {'org.opencontainers.image.ref.name': 'ubuntu', 'org.opencontainers.image.version': '22.04'}


def _labelled_by_metadata_action():
    return dict(UBUNTU, **{'org.opencontainers.image.version': '3.2.1',
                           'org.opencontainers.image.title': 'myapp',
                           'org.opencontainers.image.source': 'https://github.com/x/myapp'})


def test_the_images_own_version_is_shown():
    assert version_of(_labelled_by_metadata_action(), 'x/myapp:latest') == '3.2.1'


def test_the_info_display_reads_it_from_docker():
    facts = facts_from_attrs({'State': {}, 'HostConfig': {},
                              'Config': {'Image': 'x/myapp:latest', 'Labels': _labelled_by_metadata_action()}})
    assert facts.version == '3.2.1'


def test_a_title_alone_is_enough_to_name_itself():
    labels = dict(UBUNTU, **{'org.opencontainers.image.version': '3.2.1',
                             'org.opencontainers.image.title': 'myapp'})
    assert version_of(labels, 'x/myapp') == '3.2.1'


def test_the_pure_inheritance_stays_hidden():
    assert version_of(dict(UBUNTU), 'carmeet-api') is None
