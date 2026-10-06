"""K0: identity rules and issue pairing for the master knowledge model."""
import pytest

from asthra.knowledge.compat import pick_counterpart
from asthra.knowledge.identity import (Csn, ata_chapter, ata_from_ispec, check_cage, parse_nsn, part_key,
                                       same_part, sns_from_dmcode)


def test_part_identity():
    a = part_key("f0111", " hf 29001 ")
    assert str(a) == "F0111:HF29001" and a.qualified
    assert same_part(a, part_key("F0111", "HF29001")) == "same"
    assert same_part(a, part_key("F9999", "HF29001")) == "different"         # same number, other maker
    assert same_part(a, part_key("", "hf29001")) == "possible"               # never merged automatically
    assert same_part(part_key("A", "X-1"), part_key("A", "X1")) == "different"   # punctuation matters


def test_cage_codes():
    assert check_cage("94271").origin == "US" and check_cage("94271").ok
    assert check_cage("F0111").origin == "NATO/other" and check_cage("F0111").ok
    assert not check_cage("F011").ok and not check_cage("").ok
    assert not check_cage("8I205").ok                                         # US codes avoid I and O


def test_nsn():
    n = parse_nsn("1560-14-123-4567")
    assert n and n.supply_class == "1560" and n.country == "14" and str(n) == "1560-14-123-4567"
    assert parse_nsn("15601412345") is None


def test_breakdown_ids_link_s1000d_and_ispec():
    dm = sns_from_dmcode({"systemCode": "25", "subSystemCode": "3", "subSubSystemCode": "0", "assyCode": "12"})
    cmm = ata_from_ispec("25", "26", "62")
    assert str(dm) == "SNS:25-30-12" and str(cmm) == "ATA:25-26-62"
    assert ata_chapter(dm) == ata_chapter(cmm) == "25"                         # both: equipment/furnishings


def test_csn_forms():
    c = Csn.from_s1000d({"systemCode": "25", "subSystemCode": "3", "subSubSystemCode": "0", "assyCode": "12",
                         "figureNumber": "01", "figureNumberVariant": "", "item": "7", "itemVariant": "A"})
    assert c.s2000m() == "25301201 007A" and len(c.s2000m()) == 13
    long = Csn("D00", "0", "0", "0000", "1", "A", "12")
    assert len(long.s2000m()) == 16
    with pytest.raises(ValueError):
        Csn("25", "3", "0", "123", "01").s2000m()


def test_issue_pairing():
    inst = [("S1000D", "4.1"), ("S1000D", "6"), ("S2000M", "7.0"), ("S3000L", "2.0"), ("S3000L", "1.1")]
    p = pick_counterpart(inst, ("S2000M", "7.0"), "S3000L")
    assert p.issue == "2.0" and p.how == "block release"
    p = pick_counterpart(inst, ("S1000D", "6"), "S2000M")
    assert p.issue == "7.0" and p.how == "only installed issue" and "check" in p.note
    assert pick_counterpart(inst, ("S1000D", "6"), "S3000L").how == "choose"
    assert pick_counterpart(inst, ("S1000D", "6"), "S4000P").how == "not installed"
    rule = [{"name": "Project X", "S1000D": "6", "S3000L": "1.1"}]
    assert pick_counterpart(inst, ("S1000D", "6"), "S3000L", rule).issue == "1.1"
