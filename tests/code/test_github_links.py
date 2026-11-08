import pytest

from module_agent.code.domain.github_links import (
    declared_implementation_links,
    repository_key,
)


@pytest.mark.parametrize(
    "text",
    [
        "Our code is publicly available at: https://github.com/alice/model.",
        "Codes are released on~\\url{https://github.com/alice/model}.",
        "The source code is available at https://github.com/alice/model.git.",
        "Implementation: https://github.com/alice/model",
        "本文代码已开源：https://github.com/alice/model。",
    ],
)
def test_declared_code_address_is_recognized(text: str) -> None:
    assert declared_implementation_links(text) == ["https://github.com/alice/model"]


@pytest.mark.parametrize(
    "text",
    [
        "We use benchmark https://github.com/alice/model.",
        "The baseline code is available at https://github.com/alice/model.",
        "For related work see https://github.com/alice/model.",
        "Our code is not released. We compare https://github.com/alice/model.",
        "Our code is not available at https://github.com/alice/model.",
        "Our code: https://github.com/ours/code. See also https://github.com/alice/model.",
    ],
)
def test_reference_link_does_not_inherit_code_declaration(text: str) -> None:
    assert "https://github.com/alice/model" not in declared_implementation_links(text)


def test_code_declaration_after_benchmark_link_is_not_lost() -> None:
    text = (
        "We compare https://github.com/baseline/bench. "
        "Our code is at https://github.com/ours/code."
    )
    assert declared_implementation_links(text) == ["https://github.com/ours/code"]


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/ALICE/Model.git?tab=readme",
        "https://www.github.com/alice/model/tree/main/src",
        "http://github.com/alice/model/",
    ],
)
def test_repository_identity_normalizes_git_paths_and_case(url: str) -> None:
    assert repository_key(url) == "alice/model"


@pytest.mark.parametrize(
    "url",
    [
        "https://publisher.test/?redirect=https://github.com/alice/model",
        "https://github.com.evil.test/alice/model",
        "https://github.com@evil.test/alice/model",
        "https://user:password@github.com/alice/model",
        "ftp://github.com/alice/model",
        "https://github.com/topics/machine-learning",
        "https://github.com/alice/model-incorrect",
    ],
)
def test_other_urls_do_not_match_repository_identity(url: str) -> None:
    assert repository_key(url) != "alice/model"
