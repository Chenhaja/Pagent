from app.tools.subagents.file_policy import FileToolPolicy


def test_file_policy_allows_read_root() -> None:
    """readRoots 内的路径应允许读取。"""
    policy = FileToolPolicy(readRoots=["docs/"])

    assert policy.check("read", "docs/spec.md") == "docs/spec.md"


def test_file_policy_denies_read_by_default() -> None:
    """未显式配置读取权限时应默认拒绝。"""
    policy = FileToolPolicy()

    assert policy.can_read("docs/spec.md") is False


def test_file_policy_allows_write_root() -> None:
    """writeRoots 内的路径应允许写入。"""
    policy = FileToolPolicy(writeRoots=["outputs/"])

    assert policy.check("write", "outputs/result.md") == "outputs/result.md"


def test_file_policy_denies_write_by_default() -> None:
    """未显式配置写权限时应默认拒绝写入。"""
    policy = FileToolPolicy(readRoots=["outputs/"])

    assert policy.can_write("outputs/result.md") is False


def test_file_policy_deny_globs_have_priority() -> None:
    """denyGlobs 应优先于前缀允许规则。"""
    policy = FileToolPolicy(readRoots=["docs/"], writeRoots=["docs/"], denyGlobs=["docs/secrets/**"])

    assert policy.can_read("docs/secrets/token.txt") is False
    assert policy.can_write("docs/secrets/token.txt") is False


def test_file_policy_allow_globs_refine_allowed_roots() -> None:
    """allowGlobs 应能细化 root 内允许访问的文件。"""
    policy = FileToolPolicy(readRoots=["docs/"], allowGlobs=["docs/**/*.md"])

    assert policy.can_read("docs/specs/a.md") is True
    assert policy.can_read("docs/specs/a.txt") is False


def test_file_policy_rejects_path_escape_and_absolute_path() -> None:
    """路径逃逸和绝对路径应被拒绝。"""
    policy = FileToolPolicy(readRoots=["docs/"], writeRoots=["outputs/"])

    assert policy.can_read("../docs/spec.md") is False
    assert policy.can_read("/docs/spec.md") is False
    assert policy.can_write("outputs/../secret.md") is False


def test_file_policy_default_sensitive_patterns_are_denied() -> None:
    """默认敏感模式应拒绝访问。"""
    policy = FileToolPolicy(readRoots=["docs/", "secrets/"], writeRoots=["docs/", "secrets/"])

    assert policy.can_read("docs/.env") is False
    assert policy.can_read("secrets/api.txt") is False
    assert policy.can_read("docs/cert.pem") is False
    assert policy.can_write("docs/private.key") is False
