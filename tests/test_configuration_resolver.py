from lib.services.configuration import ConfigurationResolver

def test_precedence_and_provenance():
    r=ConfigurationResolver().resolve(defaults={"x":1,"nested":{"a":1}},environment={"x":2},lab={"x":3},run={"nested":{"a":4}},test_override={"x":5})
    assert r.values["x"]==5
    assert r.values["nested"]["a"]==4
    assert r.provenance["x"]==("defaults","environment","lab","test_override")
