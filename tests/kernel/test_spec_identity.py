from kernel.spec_identity import spec_identity_aliases


def test_slug_exposes_numeric_compatibility_alias() -> None:
    assert spec_identity_aliases("906-cli-output-styling") == (
        "906-cli-output-styling",
        "906",
    )


def test_numeric_and_nonnumeric_values_stay_stable() -> None:
    assert spec_identity_aliases("906") == ("906",)
    assert spec_identity_aliases("feature-without-number") == (
        "feature-without-number",
    )
