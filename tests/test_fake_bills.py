import random

from bill_onboard.checks import check_bill
from bill_onboard.fake_bills import FAULTS, make_bill, plant_fault


def test_generated_bills_pass_all_checks():
    rng = random.Random(7)
    for _ in range(200):
        assert check_bill(make_bill(rng, "Northwind Energy")) == []


def test_every_planted_fault_is_caught():
    rng = random.Random(11)
    for fault in FAULTS:
        for _ in range(50):
            assert check_bill(plant_fault(make_bill(rng, "Northwind Energy"), fault, rng)) != []
