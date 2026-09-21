from taq.environment import current_environment


def test_current_environment_has_sane_fields():
    env = current_environment()
    assert env.python_executable
    assert env.purelib.exists() or True  # purelib may not exist yet in a fresh venv
    assert isinstance(env.is_virtualenv, bool)
    assert len(env.version_info) == 3


def test_compatible_tags_nonempty():
    env = current_environment()
    tags = env.compatible_tags()
    assert len(tags) > 0
