from asthra.validation.explain import explain
from tests.conftest import DOCS

UNITS = "{'Pa', 'kPa', 'MPa', 'mPa', 'GPa', 'N.m', 'in', 'mm'}"


def test_enumeration_near_miss_offers_verified_fix():
    msg, sugg, attr, val, fix = explain(
        f"Element 'quantityValue', attribute 'quantityUnitOfMeasure': [facet 'enumeration'] The value 'Mpa' is not an element of the set {UNITS}.")
    assert attr == "quantityUnitOfMeasure" and val == "Mpa"
    # 'Mpa' is case-insensitively both MPa (mega) and mPa (milli): a factor of 10^9 apart.
    # That is an engineering decision, so both are suggested and no automatic fix is offered.
    assert "'MPa'" in sugg and "'mPa'" in sugg and fix is None
    assert len(msg) < 120                                 # no giant value list in the message
    *_, fix2 = explain("Element 'q', attribute 'u': [facet 'enumeration'] The value 'kpa' is not an element of the set {'kPa', 'Pa', 'MPa'}.")
    assert fix2 and fix2.value == "kPa"                   # a single unambiguous match is offered


def test_enumeration_small_set_lists_values():
    msg, sugg, attr, val, fix = explain(
        "Element 'quantityTolerance', attribute 'quantityToleranceType': [facet 'enumeration'] The value 'plusminus' is not an element of the set {'plus', 'minus', 'plusorminus'}.")
    assert fix and fix.value == "plusorminus"


def test_decimal_comma_fix_but_never_fraction_conversion():
    *_, fix = explain("Element 'quantityValue': '0,079' is not a valid value of the atomic type 'xs:decimal'.")
    assert fix and fix.value == "0.079" and fix.kind == "text"
    msg, sugg, _, _, fix2 = explain("Element 'quantityValue': '3/7' is not a valid value of the atomic type 'xs:decimal'.")
    assert fix2 is None and "0.4286" in sugg and "precision" in sugg


def test_pattern_padding_fix_is_checked_against_the_pattern():
    *_, fix = explain("Element 'issueInfo', attribute 'issueNumber': [facet 'pattern'] The value '1' is not accepted by the pattern '[0-9]{3}'.")
    assert fix and fix.value == "001"
    *_, none = explain("Element 'x', attribute 'y': [facet 'pattern'] The value 'ab' is not accepted by the pattern '[0-9]{3}'.")
    assert none is None


def test_structure_messages_are_readable():
    msg, sugg, *_ = explain("Element 'caution': This element is not expected. Expected is one of ( figure, proceduralStep ).")
    assert msg == "<caution> is not allowed at this position." and "<figure>" in sugg
    msg, sugg, attr, *_ = explain("Element 'issueInfo': The attribute 'inWork' is required but missing.")
    assert attr == "inWork" and "missing" in msg


def test_pipeline_attaches_explanations(loaded, project):
    d = loaded.documents.import_path(project["id"], DOCS / "s1000d_proced_invalid.xml")
    rep = loaded.documents.validate(d["id"])
    pat = next(x for x in rep.diagnostics if x.attribute == "issueNumber")
    assert pat.fix and pat.fix.value == "001" and pat.raw_message.startswith("Element 'issueInfo'")
    ref = loaded.documents.import_path(project["id"], DOCS / "s2000m_provisioning_invalid.xml")
    r2 = loaded.documents.validate(ref["id"])
    idref = next(x for x in r2.diagnostics if x.rule_id == "XSD-IDREF")
    assert idref.attribute == "partRef" and idref.value == "p9"
