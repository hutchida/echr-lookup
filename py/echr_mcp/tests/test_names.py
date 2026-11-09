import pytest

from echr_mcp.common import cite, display_case_name


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("CHAHAL v. THE UNITED KINGDOM", "Chahal v. the United Kingdom"),
        ("McCANN AND OTHERS v. THE UNITED KINGDOM", "McCann and Others v. the United Kingdom"),
        (
            "OTHMAN (ABU QATADA) v. THE UNITED KINGDOM",
            "Othman (Abu Qatada) v. the United Kingdom",
        ),
        ("Othman (Abu Qatada) v. the United Kingdom", "Othman (Abu Qatada) v. the United Kingdom"),
        ("Saadi v. the United Kingdom [GC]", "Saadi v. the United Kingdom [GC]"),
        ("Khaksar v. the United Kingdom (dec.)", "Khaksar v. the United Kingdom (dec.)"),
        (
            "AL-SKEINI AND OTHERS v. THE UNITED KINGDOM",
            "Al-Skeini and Others v. the United Kingdom",
        ),
        ("A.H. KHAN v. THE UNITED KINGDOM", "A.H. Khan v. the United Kingdom"),
        ("K2 v. THE UNITED KINGDOM", "K2 v. the United Kingdom"),
        ("HIRST v. THE UNITED KINGDOM (No. 2)", "Hirst v. the United Kingdom (No. 2)"),
        ("Human Rights Act 1998", "Human Rights Act 1998"),
        ("CASE OF SOERING v. THE UNITED KINGDOM", "Soering v. the United Kingdom"),
    ],
)
def test_display_case_name(raw, shown):
    assert display_case_name(raw) == shown


def test_display_case_name_is_idempotent():
    once = display_case_name("MCCANN AND OTHERS v. THE UNITED KINGDOM")
    assert display_case_name(once) == once


def test_cite_format_and_brackets_in_names():
    assert (
        cite("CHAHAL v. THE UNITED KINGDOM", "judgment", "§79")
        == "[Chahal v. the United Kingdom, Judgment, §79]"
    )
    assert cite("Saadi v. the United Kingdom [GC]", "judgment", "Operative provisions, para 3") == (
        "[Saadi v. the United Kingdom (GC), Judgment, Operative provisions, para 3]"
    )
    assert cite("X v. UK", "legal_summary", "Law, para 2").endswith("Legal summary, Law, para 2]")
